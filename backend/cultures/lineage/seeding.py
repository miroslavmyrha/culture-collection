"""What seed_dev and seed_e2e make of lineage, through the lineage services: passages, batches
of vials (placed into a box in fill order, or not placed), checks of batches and releases.

A strain's batches are created in the order listed, and a strain that has as many as listed
gets no more. A batch's checks are recorded in the order listed, and a batch that has as many
as listed gets no more. A release is made only for a batch still pending its checks. A box is
found by its path when its batch is made.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from cultures.labs.access import Access
from cultures.labs.models import Lab
from cultures.storage.seeding import unit_at
from cultures.strains.models import Strain

from . import services
from .models import (
    Batch,
    BatchCheck,
    BatchStatus,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStage,
    CheckUnit,
    Method,
    Passage,
    Purpose,
    Vial,
)

# The three checks a release needs, all passed (seed_e2e's released stock).
PASSED_FOR_RELEASE = (
    (CheckKind.IDENTITY, CheckMethod.SEQUENCING),
    (CheckKind.PURITY, CheckMethod.STREAK_PLATE),
    (CheckKind.VIABILITY, CheckMethod.GROWTH),
)


@dataclass(frozen=True)
class SeedBatch:
    method: Method
    purpose: Purpose
    preserved_on: date
    vial_count: int
    cryoprotectant: str = ""
    passage: int = 0  # grown by subculture from the one before when the strain lacks it
    box: Sequence[str] = field(default_factory=tuple)  # the box's path of names; empty: unplaced


@dataclass(frozen=True)
class SeedCheck:
    kind: CheckKind
    stage: CheckStage
    checked_on: date
    method: CheckMethod
    result: CheckResult
    method_detail: str = ""
    value: Decimal | None = None
    unit: CheckUnit | None = None
    vial: int | None = None  # the vial's number in its batch
    note: str = ""


def passage(access: Access, strain: Strain, number: int) -> Passage:
    """The strain's passage with this number, grown by subculture from the one before."""
    found = Passage.objects.filter(strain=strain, number=number).order_by("pk").first()
    if found is not None:
        return found
    parent = passage(access, strain, number - 1)
    return services.passage_subculture(access=access, parent=parent)


def _preserve(access: Access, strain: Strain, data: SeedBatch) -> Batch:
    grown = passage(access, strain, data.passage)
    return services.batch_preserve(
        access=access,
        passage=grown,
        data=services.NewBatch(
            method=data.method,
            purpose=data.purpose,
            preserved_on=data.preserved_on,
            vial_count=data.vial_count,
            cryoprotectant=data.cryoprotectant,
            box=unit_at(strain.lab, data.box) if data.box else None,
        ),
    )


def batches(access: Access, strain: Strain, rows: Sequence[SeedBatch]) -> tuple[int, int]:
    """The strain's batches, preserved by `access`. Returns how many were created and found."""
    made = Batch.objects.filter(strain=strain).count()
    for row in rows[made:]:
        _preserve(access, strain, row)
    return len(rows[made:]), min(made, len(rows))


def batch_of(lab: Lab, deposit_name: str, number: int) -> Batch:
    """The batch with this number of the strain a deposit of the lab made."""
    return Batch.objects.get(lab=lab, strain__deposit__name_as_received=deposit_name, number=number)


def _record(access: Access, batch: Batch, data: SeedCheck) -> None:
    services.check_record(
        access=access,
        batch=batch,
        data=services.NewCheck(
            kind=data.kind,
            stage=data.stage,
            checked_on=data.checked_on,
            method=data.method,
            result=data.result,
            method_detail=data.method_detail,
            value=data.value,
            unit=data.unit,
            vial=Vial.objects.get(batch=batch, seq=data.vial) if data.vial else None,
            note=data.note,
        ),
    )


def checks(access: Access, batch: Batch, rows: Sequence[SeedCheck]) -> tuple[int, int]:
    """The batch's checks, recorded by `access`. Returns how many were created and found."""
    made = BatchCheck.objects.filter(batch=batch).count()
    for row in rows[made:]:
        _record(access, batch, row)
    return len(rows[made:]), min(made, len(rows))


def release(access: Access, batch: Batch, reason: str) -> None:
    """Released by `access`, when the batch still waits for its checks."""
    if batch.status == BatchStatus.PENDING_CHECK:
        services.batch_release(access=access, batch=batch, reason=reason)


def released_batch(
    bench: Access,
    curator: Access,
    strain: Strain,
    data: SeedBatch,
    *,
    checked_on: date,
    reason: str,
) -> None:
    """A new batch, preserved by `bench`, its first vial passing every check a release needs
    (recorded by `bench`), released by `curator`. Each call makes one."""
    batch = _preserve(bench, strain, data)
    for kind, method in PASSED_FOR_RELEASE:
        _record(
            bench,
            batch,
            SeedCheck(
                kind, CheckStage.AFTER_PRESERVATION, checked_on, method, CheckResult.PASS, vial=1
            ),
        )
    services.batch_release(access=curator, batch=batch, reason=reason)
