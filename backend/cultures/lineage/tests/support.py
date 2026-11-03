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

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.biosafety.models import DestructionMethod
from cultures.biosafety.policy import permit_today
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
    DestructionRecord,
    DestructionVial,
    Method,
    Passage,
    Purpose,
    Vial,
    VialPlacement,
    VialStatus,
)
from cultures.storage.models import StorageUnit
from cultures.strains import services as strains
from cultures.strains.models import DeaccessionCause, FinalUse, Strain, StrainStatus
from cultures.strains.tests.conftest import LAB_ID
from cultures.users.models import User

LAB_URL = f"/api/v1/labs/{LAB_ID}"
PASSAGES_URL = f"{LAB_URL}/passages/"
BATCHES_URL = f"{LAB_URL}/batches/"
VIALS_URL = f"{LAB_URL}/vials/"
GRANTS_URL = f"{LAB_URL}/location-grants/"
CHECKS_URL = f"{LAB_URL}/batch-checks/"
DESTRUCTIONS_URL = f"{LAB_URL}/destructions/"
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


def released(technician: User, curator: User, batch: Batch) -> Batch:
    """The batch past its three checks and released by the curator (the technician's checks need
    the as_technician context, the release the curator's own)."""
    pass_all(technician, batch)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-c"):
        return services.batch_release(
            access=access_for(curator),
            batch=batch,
            reason="all three checks after preservation passed",
        )


PLATE_COUNT = {"value": Decimal("250000000"), "unit": CheckUnit.CFU_PER_ML}


def vials_of(batch: Batch) -> list[Vial]:
    return list(Vial.objects.filter(batch=batch).order_by("seq"))


def open_place(vial: Vial) -> tuple[StorageUnit, int, int] | None:
    placement = VialPlacement.objects.filter(vial=vial, removed_at__isnull=True).first()
    return None if placement is None else (placement.box, placement.row, placement.col)


def snapshot() -> tuple[Any, ...]:
    """Every lineage table, every event and every row change."""
    tables = (Passage, Batch, Vial, VialPlacement, BatchCheck, DestructionRecord, DestructionVial)
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


def deaccession(
    strain: Strain, final_use: FinalUse | None, *, proposer: User, confirmer: User
) -> Strain:
    """Through the strains services, each step in its own audit context: one person for a strain
    that is not regulated, a proposal and a confirmation for a quarantine pest (#20)."""
    data = strains.Deaccession(
        DeaccessionCause.CONTAMINATED, "Mixed culture on every plate.", final_use
    )
    with audit_context(channel=Channel.API, actor=proposer, request_id="req-setup"):
        if final_use is None:
            return strains.strain_deaccession(access=access_for(proposer), strain=strain, data=data)
        proposal = strains.strain_deaccession_propose(
            access=access_for(proposer), strain=strain, data=data
        )
    with audit_context(channel=Channel.API, actor=confirmer, request_id="req-setup"):
        return strains.strain_deaccession_confirm(
            access=access_for(confirmer), strain=strain, proposal=proposal.public_id
        )


# The destruction record (#160).
VERIFIED = "Spore strip in the load: no growth after 7 days."


def new_destruction(vials: list[Vial], **changes: Any) -> services.NewDestruction:
    """Autoclaved today with a verification (what a regulated strain needs, harmless for
    another), for the reason a test does not care about."""
    values: dict[str, Any] = {
        "vials": vials,
        "destroyed_on": permit_today(),
        "method": DestructionMethod.AUTOCLAVE,
        "reason": "Contaminated on every plate.",
        "verification": VERIFIED,
        **changes,
    }
    return services.NewDestruction(**values)


def mark_to_destroy(actor: User, vials: list[Vial]) -> list[Vial]:
    """Each vial to destroy through the service, in an audit context of the actor's own."""
    with audit_context(channel=Channel.API, actor=actor, request_id="req-mark"):
        return [
            services.vial_transition(
                access=access_for(actor), vial=v, status=VialStatus.TO_DESTROY, reason="cracked"
            )
            for v in vials
        ]


def destroy(
    actor: User, vials: list[Vial], *, confirmer: User | None = None, **changes: Any
) -> DestructionRecord:
    """The destruction through the services, each step in an audit context of its own: recorded
    by `actor`, and for a regulated strain confirmed by `confirmer`."""
    strain = vials[0].batch.strain
    with audit_context(channel=Channel.API, actor=actor, request_id="req-destroy"):
        record = services.destruction_record(
            access=access_for(actor), strain=strain, data=new_destruction(vials, **changes)
        )
    if confirmer is None:
        return record
    with audit_context(channel=Channel.API, actor=confirmer, request_id="req-confirm"):
        return services.destruction_confirm(access=access_for(confirmer), record=record)
