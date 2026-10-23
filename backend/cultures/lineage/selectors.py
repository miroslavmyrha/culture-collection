"""Reads of passages, batches, their checks and vials. Every one takes the access object, so the
lab scope is in the signature.

A vial row carries `regulated` (its strain has an active restriction) and its open placement.
The serializers leave the location out of every regulated row: the list is the same for every
reader, a holder of the location grant included (ADR 0009, amendment of 2026-10-19).
"""

from collections.abc import Iterable

from django.db.models import Case, Count, Exists, F, OuterRef, Prefetch, Q, QuerySet, Subquery, When

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.storage.models import StorageUnit, UnitKind
from cultures.strains.models import StrainStatus
from cultures.strains.selectors import regulating_restrictions

from .models import (
    Batch,
    BatchCheck,
    BatchStatus,
    CheckKind,
    CheckStatus,
    Passage,
    Purpose,
    Vial,
    VialPlacement,
    VialStatus,
)

# A strain in these states may give material (deaccessioned and pending ones do not).
SUPPLYING = (StrainStatus.ACTIVE, StrainStatus.RESTRICTED)


def passage_list(*, access: Access, lab: Lab) -> QuerySet[Passage]:
    """The passages of one lab the user may view, with their sources' public ids, oldest first."""
    return (
        Passage.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("strain", "source_deposit", "source_passage", "source_vial__batch")
        .order_by("strain_id", "number", "created_at", "pk")
    )


def distributable(prefix: str = "") -> Q:
    """A batch whose vials may go out (ADR 0008, D15 and D16): released after its checks,
    distribution stock (seed stock never leaves), of a strain that still supplies. `prefix`
    reaches the batch from another model ("batch__" from a vial). The one definition: the
    batch figure and the vial selector of distribution (#18) both read it."""
    return Q(
        **{
            f"{prefix}status": BatchStatus.RELEASED,
            f"{prefix}purpose": Purpose.DISTRIBUTION,
            f"{prefix}strain__status__in": SUPPLYING,
        }
    )


def latest_result(kind: CheckKind) -> Subquery:
    """The result of the batch's latest valid check of the kind, or null (one index scan). The
    batch list shows it, and Home (#69) tells a batch to check from one to release by it."""
    return Subquery(
        BatchCheck.objects.filter(batch=OuterRef("pk"), kind=kind, status=CheckStatus.VALID)
        .order_by("-checked_on", "-pk")
        .values("result")[:1]
    )


def batch_list(*, access: Access, lab: Lab) -> QuerySet[Batch]:
    """The batches of one lab the user may view, with their passage, how many vials are still
    available and how many of them may be distributed, and the result of the latest valid check
    of each kind (`latest_identity`, `latest_purity`, `latest_viability`), by strain and
    number."""
    return (
        Batch.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("strain", "passage")
        .annotate(vials_available=Count("vials", filter=Q(vials__status=VialStatus.AVAILABLE)))
        .annotate(
            vials_distributable=Case(When(distributable(), then=F("vials_available")), default=0),
            **{f"latest_{kind}": latest_result(kind) for kind in CheckKind},
        )
        .order_by("strain_id", "number", "pk")
    )


def check_list(*, access: Access, lab: Lab) -> QuerySet[BatchCheck]:
    """The checks of one lab the user may view, entered in error included, newest first: by the
    day checked, then the order recorded."""
    return (
        BatchCheck.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("batch__strain", "performed_by", "vial", "supersedes")
        .order_by("-checked_on", "-pk")
    )


def vials_for_distribution(*, access: Access, lab: Lab, perm: Perm) -> QuerySet[Vial]:
    """The vials that may be reserved and sent (#18 relies on it): available, of a released
    distribution batch of a strain that supplies. Never a seed vial, never one of a batch
    pending its checks, on hold or exhausted. `perm` is what the caller may do with them."""
    return (
        Vial.objects.for_access(access, perm)
        .filter(lab=lab, status=VialStatus.AVAILABLE)
        .filter(distributable("batch__"))
        .select_related("batch__strain")
        .order_by("batch__strain_id", "batch__number", "seq", "pk")
    )


def _regulated() -> Exists:
    return Exists(regulating_restrictions().filter(strain_id=OuterRef("batch__strain_id")))


def vial_list(*, access: Access, lab: Lab) -> QuerySet[Vial]:
    """The vials of one lab the user may view, by strain, batch and number, each with
    `regulated` and its open placement (`open_placements`, at most one)."""
    return (
        Vial.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("batch__strain")
        .annotate(regulated=_regulated())
        .prefetch_related(
            Prefetch(
                "placements",
                queryset=VialPlacement.objects.filter(removed_at__isnull=True).select_related(
                    "box"
                ),
                to_attr="open_placements",
            )
        )
        .order_by("batch__strain_id", "batch__number", "seq", "pk")
    )


def box_list(*, access: Access, lab: Lab) -> QuerySet[StorageUnit]:
    """The boxes of one lab the user may view, retired ones included, in tree order."""
    return (
        StorageUnit.objects.for_access(access, Perm.VIEW_STORAGE)
        .filter(lab=lab, kind=UnitKind.BOX)
        .order_by("path")
    )


def box_positions(*, access: Access, box: StorageUnit) -> QuerySet[VialPlacement]:
    """The open placements of one box, each with its vial, batch and strain, and `regulated`
    (the strain has an active restriction), by row and column. One query for the whole grid.

    The serializer leaves the vial out of every regulated row: a reader learns that the position
    is taken, never by what (ADR 0009). The row is still read whole here, so a caller that
    serialises it must go through BoxPositionSerializer.
    """
    return (
        VialPlacement.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(box=box, removed_at__isnull=True)
        .select_related("vial__batch__strain")
        .annotate(
            regulated=Exists(
                regulating_restrictions().filter(strain_id=OuterRef("vial__batch__strain_id"))
            )
        )
        .order_by("row", "col", "pk")
    )


def box_paths(boxes: Iterable[StorageUnit]) -> dict[int, list[str]]:
    """The names from the root down to each box, in one query for all of them."""
    paths = {box.pk: list(box.path) for box in boxes}
    ids = {pk for path in paths.values() for pk in path}
    names = dict(StorageUnit.objects.filter(pk__in=ids).values_list("pk", "name"))
    return {box: [names[pk] for pk in path] for box, path in paths.items()}


def boxes_to_fill(access: Access) -> QuerySet[StorageUnit]:
    """The boxes a vial may be put into: any lab where the user handles vials. The service
    keeps the vial's own lab and asks may_store."""
    return StorageUnit.objects.for_access(access, Perm.HANDLE_VIALS).filter(kind=UnitKind.BOX)


def passages_to_preserve(access: Access) -> QuerySet[Passage]:
    return Passage.objects.for_access(access, Perm.HANDLE_VIALS)


def batches_to_check(access: Access) -> QuerySet[Batch]:
    """Batches of any lab where the user handles vials: the view keeps the URL's lab."""
    return Batch.objects.for_access(access, Perm.HANDLE_VIALS)


def vials_to_check(access: Access) -> QuerySet[Vial]:
    """Vials of any lab where the user handles vials: the service keeps the batch's own."""
    return Vial.objects.for_access(access, Perm.HANDLE_VIALS)


def checks_to_correct(access: Access) -> QuerySet[BatchCheck]:
    return BatchCheck.objects.for_access(access, Perm.HANDLE_VIALS)
