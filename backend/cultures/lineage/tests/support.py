"""Data and helpers for the lineage tests. Fixtures: fixtures.py, imported by conftest.py.

The lab, people and taxa are the strains tests' (Mycology, MYC, one member of every role;
the invented taxa Testella and Mockia), the storage tree the storage tests' (Freezer A, risk
group 2 at most > Rack 1 > Box 1, 9 x 9).
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone

from cultures.audit.models import AuditEvent, RowChange
from cultures.labs.access import access_for
from cultures.lineage import services
from cultures.lineage.models import (
    Batch,
    BatchCheck,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStage,
    CheckUnit,
    Method,
    Passage,
    Purpose,
    Vial,
    VialPlacement,
)
from cultures.storage.models import StorageUnit
from cultures.strains.models import DeaccessionCause, Strain, StrainStatus
from cultures.strains.tests.conftest import LAB_ID
from cultures.users.models import User

LAB_URL = f"/api/v1/labs/{LAB_ID}"
PASSAGES_URL = f"{LAB_URL}/passages/"
BATCHES_URL = f"{LAB_URL}/batches/"
VIALS_URL = f"{LAB_URL}/vials/"
GRANTS_URL = f"{LAB_URL}/location-grants/"
CHECKS_URL = f"{LAB_URL}/batch-checks/"
# A method of each kind, for checks that do not care which.
A_METHOD = {
    CheckKind.IDENTITY: CheckMethod.SEQUENCING,
    CheckKind.PURITY: CheckMethod.STREAK_PLATE,
    CheckKind.VIABILITY: CheckMethod.PLATE_COUNT,
}


def new_batch(**changes: Any) -> services.NewBatch:
    values: dict[str, Any] = {
        "method": Method.CRYO_MINUS80,
        "purpose": Purpose.DISTRIBUTION,
        "preserved_on": date(2026, 10, 1),
        "vial_count": 3,
        "cryoprotectant": "10 % glycerol",
        **changes,
    }
    return services.NewBatch(**values)


def preserve(actor: User, passage: Passage, **changes: Any) -> Batch:
    """Through the service, in the caller's audit context."""
    return services.batch_preserve(
        access=access_for(actor), passage=passage, data=new_batch(**changes)
    )


def new_check(kind: CheckKind = CheckKind.VIABILITY, **changes: Any) -> services.NewCheck:
    values: dict[str, Any] = {
        "kind": kind,
        "stage": CheckStage.AFTER_PRESERVATION,
        "checked_on": date(2026, 10, 2),
        "method": A_METHOD[kind],
        "result": CheckResult.PASS,
        **changes,
    }
    if values["result"] == CheckResult.REDUCED and "note" not in changes:
        values["note"] = "Fewer colonies than at preservation."
    return services.NewCheck(**values)


def record(
    actor: User, batch: Batch, kind: CheckKind = CheckKind.VIABILITY, **changes: Any
) -> BatchCheck:
    """A check through the service, in the caller's audit context."""
    supersedes = changes.pop("supersedes", None)
    reason = changes.pop("reason", "")
    return services.check_record(
        access=access_for(actor),
        batch=batch,
        data=new_check(kind, **changes),
        supersedes=supersedes,
        reason=reason,
    )


def pass_all(actor: User, batch: Batch, **changes: Any) -> list[BatchCheck]:
    """A passed check of each kind, in the caller's audit context."""
    return [record(actor, batch, kind, **changes) for kind in CheckKind]


PLATE_COUNT = {"value": Decimal("250000000"), "unit": CheckUnit.CFU_PER_ML}


def vials_of(batch: Batch) -> list[Vial]:
    return list(Vial.objects.filter(batch=batch).order_by("seq"))


def open_place(vial: Vial) -> tuple[StorageUnit, int, int] | None:
    placement = VialPlacement.objects.filter(vial=vial, removed_at__isnull=True).first()
    return None if placement is None else (placement.box, placement.row, placement.col)


def snapshot() -> tuple[Any, ...]:
    """Every lineage table, every event and every row change."""
    tables = (Passage, Batch, Vial, VialPlacement, BatchCheck)
    rows = tuple(list(m._default_manager.order_by("pk").values()) for m in tables)
    return (*rows, AuditEvent.objects.count(), RowChange.objects.count())


MakeBatch = Callable[..., Batch]


def deaccessioned_past_the_service(strain: Strain, by: User) -> None:
    """The strain's row as a deaccession leaves it (#20), but its vials untouched: what the
    service would mark for destruction stays, so a test sees a selector or a gate decide by the
    strain's status alone. The strain is not regulated (the guard asks no second person)."""
    Strain.objects.filter(pk=strain.pk).update(
        status=StrainStatus.DEACCESSIONED,
        deaccessioned_at=timezone.now(),
        deaccessioned_by=by,
        deaccession_cause=DeaccessionCause.NON_VIABLE,
        deaccession_reason="No growth after three revivals.",
    )
