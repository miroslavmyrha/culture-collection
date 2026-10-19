"""Every write on passages, batches, vials and placements (#16, ADR 0008 amendment of
2026-10-19), and the reveal of a regulated location (ADR 0009 amendment of the same day).

Each service runs in audited_atomic() and records its events, each naming the strain
(Change(strain_id=...), D13). Lock order, as everywhere: the lab row first
(labs.locks.lock_lab), then the strain, then the vial, then the box. Under the lab lock each
service re-reads the actor's role (vials.handle: technicians and up do the bench work), so a
member demoted after the request built its access object is refused, and reads the strain's
risk group, which changes only under the same lock. A refusal raises before anything is
written, or rolls back what was, so it changes nothing and records nothing.

The database holds the same rules on its own (migration 0004): the vial's edges, the
placement's box, lab and bounds, one open placement per vial and per position. The services
check them first, so a person gets a message, not a server error.
"""

import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max, Model
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_batch, record_event
from cultures.audit.registry import (
    BATCH_CREATED,
    PASSAGE_CREATED,
    VIAL_BARCODE_SET,
    VIAL_CREATED,
    VIAL_LOCATION_REVEALED,
    VIAL_MOVED,
    VIAL_PLACED,
    VIAL_STATUS_CHANGED,
    VIALS_CREATED,
    VIALS_PLACED,
)
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound, RuleViolation
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Membership
from cultures.labs.permissions import Perm, Role, role_has
from cultures.labs.services import holds_location_grant
from cultures.storage.models import StorageUnit
from cultures.storage.policy import may_store
from cultures.strains.models import Strain, StrainRestriction, StrainStatus

from .models import (
    BATCH_NUMBER_UNIQUE,
    EDGES,
    MAX_VIALS_PER_BATCH,
    NOT_IN_A_BOX,
    ONE_OPEN_PLACEMENT,
    POSITION_TAKEN,
    VIAL_BARCODE_UNIQUE,
    Batch,
    Method,
    Passage,
    Purpose,
    RemovalReason,
    Vial,
    VialPlacement,
    VialStatus,
)

PASSAGE = "passage"
BATCH = "batch"
VIAL = "vial"
# The states a person sets through the vial form. Reserved and distributed belong to
# distribution (#18, D19).
MANUAL_TARGETS: frozenset[VialStatus] = frozenset(VialStatus) - {
    VialStatus.RESERVED,
    VialStatus.DISTRIBUTED,
}
# A strain in these states may be grown and preserved.
LIVING = (StrainStatus.ACTIVE, StrainStatus.RESTRICTED)


class InvalidVial(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class StrainNotActive(Conflict):
    default_code = "strain_not_active"
    default_detail = "The strain is not active: nothing is grown or preserved from it."


class PositionTaken(Conflict):
    default_code = "position_taken"
    default_detail = "Another vial is in this position."


class VialNotInCollection(Conflict):
    default_code = "vial_not_in_collection"
    default_detail = "This vial has left the collection or is lost: it has no place."


class VialPlacedMeanwhile(Conflict):
    default_code = "vial_placed_meanwhile"
    default_detail = "The vial was placed at the same moment: reload and try again."


class EdgeNotAllowed(DomainError):
    """A field error on the status."""

    default_code = "transition_not_allowed"

    def __init__(
        self, detail: str | None = None, *, code: str | None = None, attr: str | None = "status"
    ) -> None:
        super().__init__(detail, code=code, attr=attr)


class BatchNumberTaken(Conflict):
    default_code = "batch_number_taken"
    default_detail = "Another batch took this number at the same moment: try again."


@dataclass(frozen=True)
class NewBatch:
    method: Method
    purpose: Purpose
    preserved_on: date
    vial_count: int
    cryoprotectant: str = ""
    # Place the new vials into this box, in fill order (row by row), or leave them unplaced.
    box: StorageUnit | None = None


@dataclass(frozen=True)
class Location:
    """Where a vial is, as a person reads it. Never in a list of a regulated strain."""

    box: StorageUnit
    path: list[str]  # the names from the root down to the box
    row: int
    col: int

    @property
    def label(self) -> str:
        return position_label(self.row, self.col)


def position_label(row: int, col: int) -> str:
    """D6: rows as letters, columns as numbers, both from 1: A1, I9."""
    return f"{chr(ord('A') + row - 1)}{col}"


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


# Passages.


def _new_passage(strain: Strain, number: int, **source: Any) -> Passage:
    passage = Passage.objects.create(lab_id=strain.lab_id, strain=strain, number=number, **source)
    values = {"number": number, **{k: _ref(v) for k, v in source.items()}}
    record_event(
        PASSAGE_CREATED,
        Change(
            PASSAGE,
            passage.public_id,
            {k: [None, v] for k, v in values.items()},
            lab_id=strain.lab_id,
            strain_id=strain.public_id,
        ),
    )
    return passage


def passage_subculture(*, access: Access, parent: Passage) -> Passage:
    """A subculture of a passage: the same strain, the parent's number plus one (D3)."""
    with audited_atomic():
        lock_lab(parent.lab_id)
        _require(access, parent.lab_id)
        fresh = Passage.objects.filter(pk=parent.pk).first()
        if fresh is None:
            raise NotFound
        strain = _living_strain(fresh.strain_id)
        return _new_passage(strain, fresh.number + 1, source_passage=fresh)


def vial_revive(*, access: Access, vial: Vial) -> Passage:
    """A vial is thawed or rehydrated and grown: it is consumed, and a passage starts from it,
    numbered one more than the passage its batch was preserved from."""
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id)
        strain = _living_strain(vial.batch.strain_id)
        locked = _locked_vial(vial)
        number = Passage.objects.get(pk=locked.batch.passage_id).number + 1
        _transition(locked, VialStatus.CONSUMED, f"Revived as passage {number}.", access)
        return _new_passage(strain, number, source_vial=locked)


# Batches.


def _check_batch(data: NewBatch) -> NewBatch:
    if not 1 <= data.vial_count <= MAX_VIALS_PER_BATCH:
        raise InvalidVial(f"A batch has 1 to {MAX_VIALS_PER_BATCH} vials.", attr="vial_count")
    if data.preserved_on > permit_today():
        raise InvalidVial("This date is in the future.", attr="preserved_on")
    return NewBatch(
        method=data.method,
        purpose=data.purpose,
        preserved_on=data.preserved_on,
        vial_count=data.vial_count,
        cryoprotectant=normalised(data.cryoprotectant),
        box=data.box,
    )


def batch_preserve(*, access: Access, passage: Passage, data: NewBatch) -> Batch:
    """One preservation of one passage: the batch, its vials numbered from 1, and with a box
    the vials placed in its free positions in fill order. All or nothing: a box with fewer
    free positions than vials refuses the whole batch."""
    data = _check_batch(data)
    with audited_atomic():
        lock_lab(passage.lab_id)
        _require(access, passage.lab_id)
        strain = _living_strain(passage.strain_id)
        box = None
        if data.box is not None:
            box = _locked_box(data.box, passage.lab_id)
            _check_may_store(box, strain)
            free = _free_positions(box)
            if len(free) < data.vial_count:
                raise InvalidVial(
                    f"This box has {len(free)} free positions, the batch {data.vial_count} vials.",
                    code="box_full",
                    attr="box",
                )
        top = Batch.objects.filter(strain=strain).aggregate(top=Max("number"))["top"] or 0
        batch = Batch(
            lab_id=strain.lab_id,
            strain=strain,
            passage=passage,
            number=top + 1,
            method=data.method,
            cryoprotectant=data.cryoprotectant,
            preserved_on=data.preserved_on,
            vial_count_created=data.vial_count,
            purpose=data.purpose,
        )
        _save(batch, {BATCH_NUMBER_UNIQUE: BatchNumberTaken()})
        values: dict[str, Any] = {
            "number": batch.number,
            "passage": str(passage.public_id),
            "method": batch.method,
            "cryoprotectant": batch.cryoprotectant,
            "preserved_on": batch.preserved_on.isoformat(),
            "vial_count_created": batch.vial_count_created,
            "purpose": batch.purpose,
            "status": batch.status,
        }
        record_event(
            BATCH_CREATED,
            Change(
                BATCH,
                batch.public_id,
                {k: [None, v] for k, v in values.items()},
                lab_id=strain.lab_id,
                strain_id=strain.public_id,
            ),
        )
        vials = Vial.objects.bulk_create(
            Vial(lab_id=strain.lab_id, batch=batch, seq=seq)
            for seq in range(1, data.vial_count + 1)
        )
        record_batch(
            VIAL_CREATED,
            VIALS_CREATED,
            [
                Change(
                    VIAL,
                    vial.public_id,
                    {
                        "batch": [None, str(batch.public_id)],
                        "seq": [None, vial.seq],
                        "status": [None, vial.status],
                    },
                    lab_id=strain.lab_id,
                    strain_id=strain.public_id,
                )
                for vial in vials
            ],
        )
        if box is not None:
            _place_all(access, strain, box, vials, _free_positions(box))
    return batch


def _place_all(
    access: Access,
    strain: Strain,
    box: StorageUnit,
    vials: list[Vial],
    free: list[tuple[int, int]],
) -> None:
    now = timezone.now()
    placements = VialPlacement.objects.bulk_create(
        VialPlacement(
            lab_id=strain.lab_id,
            vial=vial,
            box=box,
            row=row,
            col=col,
            placed_at=now,
            placed_by=access.user,
        )
        for vial, (row, col) in zip(vials, free, strict=False)
    )
    record_batch(
        VIAL_PLACED,
        VIALS_PLACED,
        [
            Change(
                VIAL,
                placement.vial.public_id,
                {"location": [None, _where(placement)]},
                lab_id=strain.lab_id,
                strain_id=strain.public_id,
            )
            for placement in placements
        ],
    )


# Vials.


def vial_place(*, access: Access, vial: Vial, box: StorageUnit, row: int, col: int) -> Vial:
    """Into a position of a box, or from one position to another (a move closes the old row
    and opens the new one). The same position again changes nothing."""
    if row < 1:
        raise InvalidVial("Rows are counted from 1.", code="outside_box", attr="row")
    if col < 1:
        raise InvalidVial("Columns are counted from 1.", code="outside_box", attr="col")
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id)
        strain = Strain.objects.get(pk=vial.batch.strain_id)
        locked = _locked_vial(vial)
        if locked.status in NOT_IN_A_BOX:
            raise VialNotInCollection
        target = _locked_box(box, locked.lab_id)
        _check_may_store(target, strain)
        assert target.rows is not None and target.cols is not None  # noqa: S101 (may_store: a box)
        if row > target.rows:
            raise InvalidVial(f"This box has {target.rows} rows.", code="outside_box", attr="row")
        if col > target.cols:
            raise InvalidVial(
                f"This box has {target.cols} columns.", code="outside_box", attr="col"
            )
        current = _open_placement(locked)
        if current is not None and (current.box_id, current.row, current.col) == (
            target.pk,
            row,
            col,
        ):
            return locked
        taken = VialPlacement.objects.filter(box=target, row=row, col=col, removed_at__isnull=True)
        if taken.exists():
            raise PositionTaken
        now = timezone.now()
        if current is not None:
            _close(current, access, RemovalReason.MOVED, now)
        placement = VialPlacement(
            lab_id=locked.lab_id,
            vial=locked,
            box=target,
            row=row,
            col=col,
            placed_at=now,
            placed_by=access.user,
        )
        _save(
            placement, {POSITION_TAKEN: PositionTaken(), ONE_OPEN_PLACEMENT: VialPlacedMeanwhile()}
        )
        record_event(
            VIAL_MOVED if current is not None else VIAL_PLACED,
            Change(
                VIAL,
                locked.public_id,
                {"location": [_where(current), _where(placement)]},
                lab_id=locked.lab_id,
                strain_id=strain.public_id,
            ),
        )
    return locked


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


def vial_transition(*, access: Access, vial: Vial, status: VialStatus, reason: str) -> Vial:
    """One step along D7, with a reason. Reserved and distributed are distribution's (#18)."""
    reason = _check_reason(reason)
    if status not in MANUAL_TARGETS:
        raise EdgeNotAllowed("Reservation and dispatch are recorded by distribution.")
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id)
        locked = _locked_vial(vial)
        if locked.status == status:
            return locked
        _transition(locked, status, reason, access)
    return locked


def vial_set_barcode(*, access: Access, vial: Vial, barcode: str) -> Vial:
    """A pre-printed or scanned code (D17), or none. Unique in the lab, also after the vial
    left: the code stays printed on the tube. The same value again changes nothing."""
    code = barcode.strip()
    if any(c.isspace() for c in code):
        raise InvalidVial("A barcode has no spaces.", attr="barcode")
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id)
        locked = _locked_vial(vial)
        new = code or None
        if locked.barcode == new:
            return locked
        old, locked.barcode = locked.barcode, new
        _save(
            locked,
            {
                VIAL_BARCODE_UNIQUE: InvalidVial(
                    "Another vial of the lab has this barcode.", code="unique", attr="barcode"
                )
            },
        )
        record_event(
            VIAL_BARCODE_SET,
            Change(
                VIAL,
                locked.public_id,
                {"barcode": [old, new]},
                lab_id=locked.lab_id,
                strain_id=locked.batch.strain.public_id,
            ),
        )
    return locked


# Locations of regulated strains (ADR 0009).


def is_regulated(strain: Strain) -> bool:
    """A strain with any active restriction."""
    return StrainRestriction.objects.filter(strain=strain, ended_at__isnull=True).exists()


def location_of(vial: Vial) -> Location | None:
    """Where the vial is now. Only for a vial whose strain is not regulated, or inside a reveal."""
    placement = (
        VialPlacement.objects.select_related("box")
        .filter(vial=vial, removed_at__isnull=True)
        .first()
    )
    if placement is None:
        return None
    above = dict(StorageUnit.objects.filter(pk__in=placement.box.path).values_list("pk", "name"))
    return Location(
        box=placement.box,
        path=[above[pk] for pk in placement.box.path],
        row=placement.row,
        col=placement.col,
    )


def vial_reveal_location(*, access: Access, vial: Vial) -> Location | None:
    """The location of a vial of a regulated strain, for a holder of the lab's location grant.

    Under the lab lock the grant and the role are read as committed now. The event (who,
    which vial, which strain, the request) is written and committed before the location is
    returned: a failed write fails the reveal. It holds no location. A vial of a strain
    without restrictions needs no grant and records nothing.
    """
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id, Perm.VIEW_STRAINS)
        strain = Strain.objects.get(pk=vial.batch.strain_id)
        if is_regulated(strain):
            if not holds_location_grant(lab_id=vial.lab_id, user=access.user):
                raise Forbidden(
                    "Only people the lab's managers named may see where regulated strains are.",
                    code="location_grant_required",
                )
            record_event(
                VIAL_LOCATION_REVEALED,
                Change(VIAL, vial.public_id, {}, lab_id=vial.lab_id, strain_id=strain.public_id),
            )
    # Read after the commit, so nothing is returned that the trail does not show.
    return location_of(vial)
