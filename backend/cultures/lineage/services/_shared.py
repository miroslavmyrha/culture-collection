"""Shared by the lineage services: entity names, input checks, locks, the vial's edge."""

import unicodedata
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    VIAL_STATUS_CHANGED,
)
from cultures.core.exceptions import DomainError, Forbidden, NotFound, RuleViolation
from cultures.labs.access import Access
from cultures.labs.models import Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.storage.models import StorageUnit
from cultures.storage.policy import may_store
from cultures.strains.models import Strain, StrainStatus

from ..models import (
    EDGES,
    NOT_IN_A_BOX,
    RemovalReason,
    Vial,
    VialPlacement,
    VialStatus,
)
from .errors import (
    EdgeNotAllowed,
    InvalidVial,
    StrainNotActive,
)

PASSAGE = "passage"
BATCH = "batch"
VIAL = "vial"
CHECK = "check"
# The states a person sets through the vial form. Reserved and distributed belong to
# distribution (#18, D19).
MANUAL_TARGETS: frozenset[VialStatus] = frozenset(VialStatus) - {
    VialStatus.RESERVED,
    VialStatus.DISTRIBUTED,
}
# A strain in these states may be grown and preserved.
LIVING = (StrainStatus.ACTIVE, StrainStatus.RESTRICTED)


def normalised(text: str) -> str:
    """One space between words, NFC."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def _check_reason(reason: str) -> str:
    text = reason.strip()
    if not text:
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return text


# Under the lab lock.


def _require(access: Access, lab_id: int, perm: Perm = Perm.HANDLE_VIALS) -> None:
    """The actor's role as committed now (caller holds the lab lock), not as the request began."""
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), perm):
        raise Forbidden


def _living_strain(strain_id: int) -> Strain:
    """The strain's row, locked: its batch numbers are taken under it."""
    strain = Strain.objects.select_for_update().filter(pk=strain_id).first()
    if strain is None:
        raise NotFound
    if strain.status not in LIVING:
        raise StrainNotActive
    return strain


def _locked_vial(vial: Vial) -> Vial:
    locked = (
        Vial.objects.select_for_update(of=("self",))
        .select_related("batch__strain")
        .filter(pk=vial.pk)
        .first()
    )
    if locked is None:
        raise NotFound
    return locked


def _locked_box(box: StorageUnit, lab_id: int, attr: str = "box") -> StorageUnit:
    """The box as committed now, locked: its positions are counted and taken under it."""
    locked = StorageUnit.objects.select_for_update().filter(pk=box.pk, lab_id=lab_id).first()
    if locked is None:
        raise InvalidVial("Invalid storage unit.", code="does_not_exist", attr=attr)
    return locked


def _check_may_store(box: StorageUnit, strain: Strain, attr: str = "box") -> None:
    """ADR 0009: a box, active along its path, with a cap at or above the strain's group."""
    decision = may_store(unit=box, risk_group=strain.risk_group)
    if not decision.allowed:
        raise InvalidVial(decision.detail, code=decision.code, attr=attr)


def _open_placement(vial: Vial) -> VialPlacement | None:
    return (
        VialPlacement.objects.select_for_update(of=("self",))
        .select_related("box")
        .filter(vial=vial, removed_at__isnull=True)
        .first()
    )


def _save(obj: Model, errors: dict[str, DomainError]) -> None:
    """The unique constraints are the final arbiter: a check before saving can race."""
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        error = errors.get(str(getattr(diag, "constraint_name", "")))
        if error is not None:
            raise error from exc
        raise


def _ref(obj: Model | None) -> str | None:
    return None if obj is None else str(obj.public_id)  # type: ignore[attr-defined]


def _where(placement: VialPlacement | None) -> dict[str, Any] | None:
    if placement is None:
        return None
    return {"box": _ref(placement.box), "row": placement.row, "col": placement.col}


def _fill_order(box: StorageUnit) -> Iterator[tuple[int, int]]:
    """Every position of the box, row by row: A1, A2, ..., B1."""
    assert box.rows is not None and box.cols is not None  # noqa: S101 (a box has a size)
    for row in range(1, box.rows + 1):
        for col in range(1, box.cols + 1):
            yield row, col


def _free_positions(box: StorageUnit) -> list[tuple[int, int]]:
    taken = set(
        VialPlacement.objects.filter(box=box, removed_at__isnull=True).values_list("row", "col")
    )
    return [position for position in _fill_order(box) if position not in taken]


def _close(placement: VialPlacement, access: Access, reason: RemovalReason, now: datetime) -> None:
    placement.removed_at = now
    placement.removed_by = access.user
    placement.removal_reason = reason
    placement.save(update_fields=["removed_at", "removed_by", "removal_reason", "updated_at"])


def _transition(locked: Vial, status: VialStatus, reason: str, access: Access) -> None:
    """Caller holds the lab lock and the vial's row. Checks the edge, closes the placement of a
    vial that leaves its box, and records one event with both."""
    old = VialStatus(locked.status)
    if status not in EDGES[old]:
        raise EdgeNotAllowed(
            f"A vial cannot go from {old.label.lower()} to {status.label.lower()}."
        )
    if status == VialStatus.ENTERED_IN_ERROR and locked.status_changed_at is not None:
        raise EdgeNotAllowed(
            "Only a vial whose state never changed can be entered in error.",
            code="vial_has_history",
        )
    now = timezone.now()
    changes: dict[str, Any] = {"status": [old, status]}
    if status in NOT_IN_A_BOX:
        current = _open_placement(locked)
        if current is not None:
            _close(current, access, RemovalReason(status), now)
            changes["location"] = [_where(current), None]
    locked.status, locked.status_changed_at = status, now
    locked.save(update_fields=["status", "status_changed_at", "updated_at"])
    record_event(
        VIAL_STATUS_CHANGED,
        Change(
            VIAL,
            locked.public_id,
            changes,
            lab_id=locked.lab_id,
            strain_id=locked.batch.strain.public_id,
        ),
        reason=reason,
    )
