"""Vials: placements and moves, states, barcodes, and the steps distribution takes."""

from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    VIAL_BARCODE_SET,
    VIAL_MOVED,
    VIAL_PLACED,
)
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.storage.models import StorageUnit
from cultures.strains.models import Strain

from ..models import (
    NOT_IN_A_BOX,
    ONE_OPEN_PLACEMENT,
    POSITION_TAKEN,
    VIAL_BARCODE_UNIQUE,
    Batch,
    BatchStatus,
    Purpose,
    RemovalReason,
    Vial,
    VialPlacement,
    VialStatus,
)
from ._shared import (
    MANUAL_TARGETS,
    VIAL,
    _check_may_store,
    _check_reason,
    _close,
    _locked_box,
    _locked_vial,
    _open_placement,
    _require,
    _save,
    _transition,
    _where,
)
from .checks import (
    _move_batch,
)
from .errors import (
    EdgeNotAllowed,
    InvalidVial,
    PositionTaken,
    VialNotAvailable,
    VialNotInCollection,
    VialPlacedMeanwhile,
    VialReserved,
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


def vial_transition(*, access: Access, vial: Vial, status: VialStatus, reason: str) -> Vial:
    """One step along D7, with a reason. Reserved and distributed are distribution's (#18):
    a reserved vial leaves its state only through its request."""
    reason = _check_reason(reason)
    if status not in MANUAL_TARGETS:
        raise EdgeNotAllowed("Reservation and dispatch are recorded by distribution.")
    with audited_atomic():
        lock_lab(vial.lab_id)
        _require(access, vial.lab_id)
        locked = _locked_vial(vial)
        if locked.status == status:
            return locked
        if locked.status == VialStatus.RESERVED:
            raise VialReserved
        _transition(locked, status, reason, access)
    return locked


# Distribution's steps (#18, D19). The caller holds the lab lock and the vial's row (locked by
# select_for_update with batch__strain), and writes the reservation in the same transaction:
# the deferred triggers of distribution 0003 hold a reserved vial and its open reservation
# together.


def vial_reserve_locked(*, access: Access, vial: Vial, reason: str) -> None:
    if vial.status != VialStatus.AVAILABLE:
        raise VialNotAvailable
    _transition(vial, VialStatus.RESERVED, _check_reason(reason), access)


def vial_release_locked(*, access: Access, vial: Vial, reason: str) -> None:
    if vial.status != VialStatus.RESERVED:
        raise VialNotAvailable("This vial is not reserved.")
    _transition(vial, VialStatus.AVAILABLE, _check_reason(reason), access)


def vial_ship_locked(*, access: Access, vial: Vial, reason: str) -> None:
    """The reserved vial leaves with its shipment (#88): distributed, its placement closed."""
    if vial.status != VialStatus.RESERVED:
        raise VialNotAvailable("This vial is not reserved.")
    _transition(vial, VialStatus.DISTRIBUTED, _check_reason(reason), access)


def batch_exhaust_if_emptied_locked(*, batch: Batch, reason: str) -> bool:
    """After a shipment (#88): a distribution batch with no vial left available or reserved
    becomes exhausted, with the reason. A vial in quarantine or lost does not keep it open (ADR
    0008 amendment of 2026-10-22). The caller holds the lab lock and the batch's row (locked
    before its vials) and has written the vials' new states. True when it moved."""
    if batch.purpose != Purpose.DISTRIBUTION or batch.status == BatchStatus.EXHAUSTED:
        return False
    if Vial.objects.filter(
        batch=batch, status__in=(VialStatus.AVAILABLE, VialStatus.RESERVED)
    ).exists():
        return False
    _move_batch(batch, BatchStatus.EXHAUSTED, _check_reason(reason))
    return True


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
