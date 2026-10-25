"""The checks of a batch, and its release and hold (#17)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    BATCH_CHECK_ENTERED_IN_ERROR,
    BATCH_CHECK_RECORDED,
    BATCH_STATUS_CHANGED,
)
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import NotFound
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.permissions import Perm

from ..models import (
    BATCH_EDGES,
    CHECK_VALUE_PLACES,
    MAX_PERCENT,
    METHODS_BY_KIND,
    PASSING,
    Batch,
    BatchCheck,
    BatchStatus,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStage,
    CheckStatus,
    CheckUnit,
    Vial,
    VialStatus,
)
from ._shared import (
    BATCH,
    CHECK,
    _check_reason,
    _locked_vial,
    _ref,
    _require,
    _transition,
    normalised,
)
from .errors import (
    BatchEdgeNotAllowed,
    BatchExhausted,
    CheckEnteredInError,
    ChecksNotPassed,
    InvalidCheck,
    VialNotAvailable,
)

# Checks of a batch and its release (#17, ADR 0008, D16, amendment of 2026-10-20).


@dataclass(frozen=True)
class NewCheck:
    kind: CheckKind
    stage: CheckStage
    checked_on: date
    method: CheckMethod
    result: CheckResult
    # The method in words: required for `other`.
    method_detail: str = ""
    value: Decimal | None = None
    unit: CheckUnit | None = None
    # The vial thawed or opened for the check: an available one is consumed by it.
    vial: Vial | None = None
    # What was seen: required for a reduced result.
    note: str = ""


VALUE_STEP = Decimal(1).scaleb(-CHECK_VALUE_PLACES)


def kinds_text(kinds: list[CheckKind]) -> str:
    """identity; identity and purity; identity, purity and viability."""
    names = [kind.label.lower() for kind in kinds]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _check_input(data: NewCheck) -> NewCheck:
    detail = normalised(data.method_detail)
    note = data.note.strip()
    if data.method not in METHODS_BY_KIND[data.kind]:
        raise InvalidCheck(
            f"{data.method.label} is not a method of a {data.kind.label.lower()} check.",
            attr="method",
        )
    if data.method == CheckMethod.OTHER and not detail:
        raise InvalidCheck("Describe the method.", code="required", attr="method_detail")
    if (data.value is None) != (data.unit is None):
        missing = "unit" if data.unit is None else "value"
        raise InvalidCheck(
            "Give the value with its unit, or neither.", code="required", attr=missing
        )
    if data.value is not None and data.value < 0:
        raise InvalidCheck("A value is 0 or more.", attr="value")
    if data.unit == CheckUnit.PERCENT and data.value is not None and data.value > MAX_PERCENT:
        raise InvalidCheck("A percentage is at most 100.", attr="value")
    if data.result == CheckResult.REDUCED and not note:
        raise InvalidCheck("Say what was reduced.", code="required", attr="note")
    if data.checked_on > permit_today():
        raise InvalidCheck("This date is in the future.", attr="checked_on")
    return NewCheck(
        kind=data.kind,
        stage=data.stage,
        checked_on=data.checked_on,
        method=data.method,
        result=data.result,
        method_detail=detail,
        # As the column stores it, so the event holds the stored value.
        value=None if data.value is None else data.value.quantize(VALUE_STEP),
        unit=data.unit,
        vial=data.vial,
        note=note,
    )


def _locked_batch(batch_id: int) -> Batch:
    """The batch as committed now, locked: its status is decided under it."""
    locked = (
        Batch.objects.select_for_update(of=("self",))
        .select_related("strain")
        .filter(pk=batch_id)
        .first()
    )
    if locked is None:
        raise NotFound
    return locked


def latest_checks(batch: Batch) -> dict[CheckKind, BatchCheck]:
    """The latest valid check of each kind of the batch: by the day checked, then the order
    recorded. A kind never checked, or whose checks were all entered in error, is missing."""
    rows = (
        BatchCheck.objects.filter(batch=batch, status=CheckStatus.VALID)
        .order_by("kind", "-checked_on", "-pk")
        .distinct("kind")
    )
    return {CheckKind(row.kind): row for row in rows}


def not_passed(latest: dict[CheckKind, BatchCheck]) -> list[CheckKind]:
    """The kinds whose latest valid check did not pass (reduced counts as passed): the release
    rule of ADR 0008, D16."""
    return [k for k in CheckKind if k not in latest or latest[k].result not in PASSING]


def _move_batch(locked: Batch, status: BatchStatus, reason: str) -> None:
    """Caller holds the lab lock and the batch's row. One step along BATCH_EDGES, recorded."""
    old = BatchStatus(locked.status)
    if status not in BATCH_EDGES[old]:
        raise BatchEdgeNotAllowed(
            f"A batch cannot go from {old.label.lower()} to {status.label.lower()}."
        )
    locked.status, locked.status_reason, locked.status_changed_at = status, reason, timezone.now()
    locked.save(update_fields=["status", "status_reason", "status_changed_at", "updated_at"])
    record_event(
        BATCH_STATUS_CHANGED,
        Change(
            BATCH,
            locked.public_id,
            {"status": [old, status]},
            lab_id=locked.lab_id,
            strain_id=locked.strain.public_id,
        ),
        reason=reason,
    )


def _settle(locked: Batch) -> None:
    """After a check was recorded or entered in error, the moves the checks make on their own,
    only towards safety: the latest valid check of a kind failed, so the batch is held; a
    released batch lost a passed check it was released on, so it waits for its checks again.
    Never a release: that is a curator's decision."""
    latest = latest_checks(locked)
    failed = [k for k in CheckKind if k in latest and latest[k].result == CheckResult.FAIL]
    if failed and locked.status in {BatchStatus.PENDING_CHECK, BatchStatus.RELEASED}:
        days = sorted({latest[k].checked_on.isoformat() for k in failed})
        _move_batch(
            locked,
            BatchStatus.ON_HOLD,
            f"The {kinds_text(failed)} check of {', '.join(days)} failed.",
        )
    elif not failed and locked.status == BatchStatus.RELEASED and not_passed(latest):
        _move_batch(
            locked,
            BatchStatus.PENDING_CHECK,
            f"No valid {kinds_text(not_passed(latest))} check is left after a correction.",
        )


def _enter_in_error(check: BatchCheck, reason: str, batch: Batch) -> None:
    check.status, check.reason = CheckStatus.ENTERED_IN_ERROR, reason
    check.save(update_fields=["status", "reason", "updated_at"])
    record_event(
        BATCH_CHECK_ENTERED_IN_ERROR,
        Change(
            CHECK,
            check.public_id,
            {"status": [CheckStatus.VALID, CheckStatus.ENTERED_IN_ERROR]},
            lab_id=batch.lab_id,
            strain_id=batch.strain.public_id,
        ),
        reason=reason,
    )


def check_record(
    *,
    access: Access,
    batch: Batch,
    data: NewCheck,
    supersedes: BatchCheck | None = None,
    reason: str = "",
) -> BatchCheck:
    """One check of a batch, by the person who made it. An available vial named as the one
    checked is consumed; a vial another check of this batch consumed may serve again (one
    plate shows growth and purity). A check that supersedes another enters that one in error
    with the reason. Then the batch moves when the checks ask for it (_settle)."""
    data = _check_input(data)
    if supersedes is not None:
        reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(batch.lab_id)
        _require(access, batch.lab_id)
        locked = _locked_batch(batch.pk)
        if locked.status == BatchStatus.EXHAUSTED:
            raise BatchExhausted
        if data.checked_on < locked.preserved_on:
            raise InvalidCheck(
                f"The batch was preserved on {locked.preserved_on.isoformat()}: a check is not"
                " dated before.",
                attr="checked_on",
            )
        old = None
        if supersedes is not None:
            old = BatchCheck.objects.select_for_update().filter(pk=supersedes.pk).first()
            if old is None or old.batch_id != locked.pk or old.kind != data.kind:
                raise InvalidCheck(
                    "Invalid check: a check corrects one of the same batch and kind.",
                    code="does_not_exist",
                    attr="supersedes",
                )
            if old.status != CheckStatus.VALID:
                raise CheckEnteredInError
        vial = None
        if data.vial is not None:
            vial = _locked_vial(data.vial)
            if vial.batch_id != locked.pk:
                raise InvalidCheck("Invalid vial.", code="does_not_exist", attr="vial")
            if vial.status == VialStatus.AVAILABLE:
                _transition(
                    vial,
                    VialStatus.CONSUMED,
                    f"Used for a {data.kind.label.lower()} check of batch {locked.number}.",
                    access,
                )
            elif not (
                vial.status == VialStatus.CONSUMED and BatchCheck.objects.filter(vial=vial).exists()
            ):
                raise VialNotAvailable
        check = BatchCheck.objects.create(
            lab_id=locked.lab_id,
            batch=locked,
            kind=data.kind,
            stage=data.stage,
            checked_on=data.checked_on,
            performed_by=access.user,
            method=data.method,
            method_detail=data.method_detail,
            result=data.result,
            value=data.value,
            unit=data.unit or "",
            vial=vial,
            note=data.note,
            supersedes=old,
        )
        values: dict[str, Any] = {
            "batch": str(locked.public_id),
            "kind": check.kind,
            "stage": check.stage,
            "checked_on": check.checked_on.isoformat(),
            "method": check.method,
            "method_detail": check.method_detail,
            "result": check.result,
            "value": None if check.value is None else str(check.value),
            "unit": check.unit,
            "vial": _ref(vial),
            "note": check.note,
            "supersedes": _ref(old),
        }
        record_event(
            BATCH_CHECK_RECORDED,
            Change(
                CHECK,
                check.public_id,
                {k: [None, v] for k, v in values.items()},
                lab_id=locked.lab_id,
                strain_id=locked.strain.public_id,
            ),
        )
        if old is not None:
            _enter_in_error(old, reason, locked)
        _settle(locked)
    return check


def check_enter_in_error(*, access: Access, check: BatchCheck, reason: str) -> BatchCheck:
    """A check that was wrong (the wrong batch, a typing error) leaves the release rule, with a
    reason. The row stays. A released batch that lost a passed check waits for its checks again."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(check.lab_id)
        _require(access, check.lab_id)
        locked = _locked_batch(check.batch_id)
        row = BatchCheck.objects.select_for_update().filter(pk=check.pk).first()
        if row is None:
            raise NotFound
        if row.status != CheckStatus.VALID:
            raise CheckEnteredInError
        _enter_in_error(row, reason, locked)
        if locked.status != BatchStatus.EXHAUSTED:
            _settle(locked)
    return row


def batch_release(*, access: Access, batch: Batch, reason: str) -> Batch:
    """A curator releases a batch for use: only while the latest valid identity, purity and
    viability checks passed (reduced counts as passed, its check says why). Released again
    changes nothing."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(batch.lab_id)
        _require(access, batch.lab_id, Perm.RELEASE_BATCHES)
        locked = _locked_batch(batch.pk)
        if locked.status == BatchStatus.RELEASED:
            return locked
        if locked.status == BatchStatus.EXHAUSTED:
            raise BatchExhausted
        missing = not_passed(latest_checks(locked))
        if missing:
            raise ChecksNotPassed(
                "A batch is released once its latest identity, purity and viability checks"
                f" passed. Not passed yet: {kinds_text(missing)}."
            )
        _move_batch(locked, BatchStatus.RELEASED, reason)
    return locked


def batch_hold(*, access: Access, batch: Batch, reason: str) -> Batch:
    """A curator holds a batch: nothing of it is distributed until a release. Held again
    changes nothing."""
    reason = _check_reason(reason)
    with audited_atomic():
        lock_lab(batch.lab_id)
        _require(access, batch.lab_id, Perm.RELEASE_BATCHES)
        locked = _locked_batch(batch.pk)
        if locked.status == BatchStatus.ON_HOLD:
            return locked
        if locked.status == BatchStatus.EXHAUSTED:
            raise BatchExhausted
        _move_batch(locked, BatchStatus.ON_HOLD, reason)
    return locked
