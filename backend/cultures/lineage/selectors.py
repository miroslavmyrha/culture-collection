"""Reads of passages, batches and vials. Every one takes the access object, so the lab scope is
in the signature.

A vial row carries `regulated` (its strain has an active restriction) and its open placement.
The serializers leave the location out of every regulated row: the list is the same for every
reader, a holder of the location grant included (ADR 0009, amendment of 2026-10-19).
"""

from collections.abc import Iterable

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.storage.models import StorageUnit, UnitKind
from cultures.strains.models import StrainRestriction

from .models import Batch, Passage, Vial, VialPlacement, VialStatus


def passage_list(*, access: Access, lab: Lab) -> QuerySet[Passage]:
    """The passages of one lab the user may view, with their sources' public ids, oldest first."""
    return (
        Passage.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("strain", "source_deposit", "source_passage", "source_vial__batch")
        .order_by("strain_id", "number", "created_at", "pk")
    )


def batch_list(*, access: Access, lab: Lab) -> QuerySet[Batch]:
    """The batches of one lab the user may view, with their passage and how many vials are
    still available, by strain and number."""
    return (
        Batch.objects.for_access(access, Perm.VIEW_STRAINS)
        .filter(lab=lab)
        .select_related("strain", "passage")
        .annotate(vials_available=Count("vials", filter=Q(vials__status=VialStatus.AVAILABLE)))
        .order_by("strain_id", "number", "pk")
    )


def _regulated() -> Exists:
    return Exists(
        StrainRestriction.objects.filter(
            strain_id=OuterRef("batch__strain_id"), ended_at__isnull=True
        )
    )


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
