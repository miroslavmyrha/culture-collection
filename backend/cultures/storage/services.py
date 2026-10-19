"""Every write on storage: units added, changed, moved, put out of service and retired, and the
box types staff manage.

Each unit service runs in audited_atomic() and records one event. Lock order, as
everywhere: the lab row first (labs.locks.lock_lab), then the unit's row. Under
the lab lock each service re-reads the actor's role, so a curator demoted after
the request built its access object is refused. A refusal raises before
anything is written, or rolls back what was, so it changes nothing and records
nothing.

The database holds the tree on its own (migration 0003): the path trigger
refuses a parent in another lab, a kind the parent may not hold and a cycle,
and keeps every path below a moved unit right. The services check the same
rules first, so a person gets a message on the field, not a server error.

Units are never deleted (a trigger refuses it): a unit that is gone is retired,
and only once nothing is in it. A retired unit changes no more.
"""

import unicodedata
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Model
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    BOX_TYPE_CHANGED,
    BOX_TYPE_CREATED,
    STORAGE_UNIT_CHANGED,
    STORAGE_UNIT_CREATED,
    STORAGE_UNIT_MOVED,
    STORAGE_UNIT_STATUS_CHANGED,
)
from cultures.core.exceptions import Conflict, DomainError, Forbidden, NotFound, RuleViolation
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Perm, Role, role_has

from .models import (
    BOX_TYPE_NAME_UNIQUE,
    KIND_SPEC,
    MAX_COLS,
    MAX_ROWS,
    MAX_TEMPERATURE_C,
    MIN_TEMPERATURE_C,
    UNIT_BARCODE_UNIQUE,
    UNIT_NAME_UNIQUE,
    UNIT_SLOT_UNIQUE,
    BoxType,
    StorageUnit,
    UnitKind,
    UnitStatus,
    may_hold,
)

STORAGE_UNIT = "storage_unit"
BOX_TYPE = "box_type"
# Which status may follow which. Retired is final; the same status again changes nothing.
NEXT_STATUS: dict[UnitStatus, frozenset[UnitStatus]] = {
    UnitStatus.ACTIVE: frozenset({UnitStatus.OUT_OF_SERVICE, UnitStatus.RETIRED}),
    UnitStatus.OUT_OF_SERVICE: frozenset({UnitStatus.ACTIVE, UnitStatus.RETIRED}),
    UnitStatus.RETIRED: frozenset(),
}


class InvalidUnit(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class UnitRetired(Conflict):
    default_code = "unit_retired"
    default_detail = "This unit is retired and changes no more."


class UnitNotEmpty(RuleViolation):
    default_code = "unit_not_empty"
    default_detail = "The unit still holds units that are not retired: move or retire them first."


class BoxOccupied(DomainError):
    """A field error on purpose: the form shows it on the box type."""

    default_code = "box_occupied"
    default_detail = "Vials occupy positions of this box, so its size stays as it is."

    def __init__(self, detail: str | None = None, *, attr: str | None = "box_type") -> None:
        super().__init__(detail, attr=attr)


@dataclass(frozen=True)
class NewUnit:
    kind: UnitKind
    name: str
    parent: StorageUnit | None = None
    slot: int | None = None
    barcode: str = ""
    temperature_c: int | None = None
    max_risk_group: int | None = None
    box_type: BoxType | None = None


@dataclass(frozen=True)
class UnitFields:
    """What a unit's edit form changes. Kind, parent and status have their own services."""

    name: str
    barcode: str = ""
    temperature_c: int | None = None
    max_risk_group: int | None = None
    box_type: BoxType | None = None


def normalised(text: str) -> str:
    """One space between words, NFC."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def box_occupied(box: StorageUnit) -> bool:
    """Whether a vial sits in a position of the box: its rows and columns are frozen from then on.

    Nothing occupies a position before vials are placed (#16), which counts its open placements
    here. Every service that changes a box's size or retires a box asks this.
    """
    return False


# Checks on the input alone: no query, so they run before any lock.


def _check_fields(kind: UnitKind, fields: UnitFields, *, is_root: bool) -> UnitFields:
    name = normalised(fields.name)
    if not name:
        raise InvalidUnit("Enter a name.", attr="name")
    barcode = fields.barcode.strip()
    if any(c.isspace() for c in barcode):
        raise InvalidUnit("A barcode has no spaces.", attr="barcode")
    temperature = fields.temperature_c
    if temperature is not None and not MIN_TEMPERATURE_C <= temperature <= MAX_TEMPERATURE_C:
        raise InvalidUnit(
            f"Enter a temperature from {MIN_TEMPERATURE_C} to {MAX_TEMPERATURE_C} °C.",
            attr="temperature_c",
        )
    cap = fields.max_risk_group
    if cap is None and is_root:
        raise InvalidUnit(
            "A freezer or tank states the highest risk group it may hold.", attr="max_risk_group"
        )
    if cap is not None and cap not in (1, 2, 3, 4):
        raise InvalidUnit("A risk group is 1, 2, 3 or 4.", attr="max_risk_group")
    grid = KIND_SPEC[kind].grid
    if grid and fields.box_type is None:
        raise InvalidUnit("Choose the box type.", attr="box_type")
    if not grid and fields.box_type is not None:
        raise InvalidUnit("Only a box has a box type.", attr="box_type")
    return UnitFields(name, barcode, temperature, cap, fields.box_type)


def _check_slot(slot: int | None) -> None:
    if slot is not None and slot < 1:
        raise InvalidUnit("Slots are counted from 1.", attr="slot")


# Under the lab lock.


def _require_role(access: Access, lab_id: int) -> None:
    """The actor's role as committed now (caller holds the lab lock), not as the request began."""
    role = (
        Membership.objects.filter(lab_id=lab_id, user=access.user, user__is_active=True)
        .values_list("role", flat=True)
        .first()
    )
    if role is None or not role_has(Role(role), Perm.MANAGE_STORAGE):
        raise Forbidden


def _check_parent(lab_id: int, kind: UnitKind, parent: StorageUnit | None) -> None:
    """The parent as committed now: same lab, active, and a kind that may hold this one."""
    if not KIND_SPEC[kind].held_by:
        if parent is not None:
            raise InvalidUnit(
                "A freezer or tank stands on its own: nothing holds it.", attr="parent"
            )
        return
    if parent is None:
        raise InvalidUnit("Choose the unit that holds it.", attr="parent")
    if parent.lab_id != lab_id:
        # The same text as an unknown unit: the field never tells one lab from another.
        raise InvalidUnit("Invalid storage unit.", code="does_not_exist", attr="parent")
    if parent.status != UnitStatus.ACTIVE:
        raise InvalidUnit(
            "This unit is out of service or retired: nothing goes in.",
            code="parent_not_active",
            attr="parent",
        )
    if not may_hold(UnitKind(parent.kind), kind):
        raise InvalidUnit(
            f"A {UnitKind(parent.kind).label.lower()} cannot hold a {kind.label.lower()}.",
            code="kind_not_allowed",
            attr="parent",
        )


def _fresh_parent(parent: StorageUnit | None) -> StorageUnit | None:
    if parent is None:
        return None
    fresh = StorageUnit.objects.filter(pk=parent.pk).first()
    if fresh is None:
        raise InvalidUnit("Invalid storage unit.", code="does_not_exist", attr="parent")
    return fresh


def _locked_unit(unit: StorageUnit) -> StorageUnit:
    locked = StorageUnit.objects.select_for_update().filter(pk=unit.pk).first()
    if locked is None:
        raise NotFound
    if locked.is_retired:
        raise UnitRetired
    return locked


def _save(obj: Model, errors: dict[str, DomainError], **kwargs: Any) -> None:
    """The unique constraints are the final arbiter: a check before saving can race."""
    try:
        with transaction.atomic():
            obj.save(**kwargs)
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        error = errors.get(str(getattr(diag, "constraint_name", "")))
        if error is not None:
            raise error from exc
        raise


def _unique_errors() -> dict[str, DomainError]:
    """Fresh exceptions per call: a raised exception carries its traceback."""
    return {
        UNIT_NAME_UNIQUE: InvalidUnit(
            "A unit here has this name already.", code="unique", attr="name"
        ),
        UNIT_SLOT_UNIQUE: InvalidUnit("Another unit is in this slot.", code="unique", attr="slot"),
        UNIT_BARCODE_UNIQUE: InvalidUnit(
            "Another unit of the lab has this barcode.", code="unique", attr="barcode"
        ),
    }


def _public_path(unit: StorageUnit) -> list[str]:
    """The public ids from the root down to the unit: what a move event records."""
    ids = dict(StorageUnit.objects.filter(pk__in=unit.path).values_list("pk", "public_id"))
    return [str(ids[pk]) for pk in unit.path]


def _ref(obj: Model | None) -> str | None:
    return None if obj is None else str(obj.public_id)  # type: ignore[attr-defined]


def _values(unit: StorageUnit) -> dict[str, Any]:
    return {
        "name": unit.name,
        "barcode": unit.barcode,
        "temperature_c": unit.temperature_c,
        "max_risk_group": unit.max_risk_group,
        "box_type": _ref(unit.box_type),
        "rows": unit.rows,
        "cols": unit.cols,
    }


def unit_create(*, access: Access, lab: Lab, data: NewUnit) -> StorageUnit:
    """A freezer or tank on its own, or a rack or box inside an active unit of the same lab."""
    kind = UnitKind(data.kind)
    fields = _check_fields(
        kind,
        UnitFields(data.name, data.barcode, data.temperature_c, data.max_risk_group, data.box_type),
        is_root=not KIND_SPEC[kind].held_by,
    )
    _check_slot(data.slot)
    if data.slot is not None and data.parent is None:
        raise InvalidUnit("Only a unit inside another has a slot.", attr="slot")
    with audited_atomic():
        locked_lab = lock_lab(lab.pk)
        _require_role(access, locked_lab.pk)
        parent = _fresh_parent(data.parent)
        _check_parent(locked_lab.pk, kind, parent)
        box_type = fields.box_type
        unit = StorageUnit(
            lab=locked_lab,
            kind=kind,
            name=fields.name,
            parent=parent,
            slot=data.slot,
            barcode=fields.barcode or None,
            temperature_c=fields.temperature_c,
            max_risk_group=fields.max_risk_group,
            box_type=box_type,
            rows=box_type.rows if box_type else None,
            cols=box_type.cols if box_type else None,
        )
        _save(unit, _unique_errors())
        unit.refresh_from_db(fields=["path"])
        values = {
            "kind": unit.kind,
            "parent": _ref(parent),
            "slot": unit.slot,
            "status": unit.status,
            **_values(unit),
        }
        record_event(
            STORAGE_UNIT_CREATED,
            Change(
                STORAGE_UNIT,
                unit.public_id,
                {k: [None, v] for k, v in values.items()},
                lab_id=locked_lab.pk,
            ),
        )
    return unit


def unit_update(*, access: Access, unit: StorageUnit, fields: UnitFields) -> StorageUnit:
    """Name, barcode, temperature, risk group cap, and for a box its type, which sets its size
    again while no position is occupied. Nothing changed records nothing."""
    with audited_atomic():
        lock_lab(unit.lab_id)
        _require_role(access, unit.lab_id)
        locked = _locked_unit(unit)
        kind = UnitKind(locked.kind)
        checked = _check_fields(kind, fields, is_root=locked.parent_id is None)
        before = _values(locked)
        locked.name = checked.name
        locked.barcode = checked.barcode or None
        locked.temperature_c = checked.temperature_c
        locked.max_risk_group = checked.max_risk_group
        new_type = checked.box_type
        if new_type is not None and new_type.pk != locked.box_type_id:
            if box_occupied(locked):
                raise BoxOccupied
            locked.box_type, locked.rows, locked.cols = new_type, new_type.rows, new_type.cols
        after = _values(locked)
        changes = {k: [before[k], v] for k, v in after.items() if before[k] != v}
        if not changes:
            return locked
        _save(
            locked,
            _unique_errors(),
            update_fields=[
                "name",
                "barcode",
                "temperature_c",
                "max_risk_group",
                "box_type",
                "rows",
                "cols",
                "updated_at",
            ],
        )
        record_event(
            STORAGE_UNIT_CHANGED,
            Change(STORAGE_UNIT, locked.public_id, changes, lab_id=locked.lab_id),
        )
    return locked


def unit_move(
    *, access: Access, unit: StorageUnit, parent: StorageUnit, slot: int | None
) -> StorageUnit:
    """Into another active unit of the lab that may hold it, with everything it holds. Never
    into itself or anything below it. The same place again changes nothing."""
    _check_slot(slot)
    with audited_atomic():
        lock_lab(unit.lab_id)
        _require_role(access, unit.lab_id)
        locked = _locked_unit(unit)
        target = _fresh_parent(parent)
        assert target is not None  # noqa: S101 (parent is required here)
        if locked.pk in target.path:
            raise InvalidUnit(
                "A unit cannot go inside itself or a unit it holds.", code="cycle", attr="parent"
            )
        _check_parent(locked.lab_id, UnitKind(locked.kind), target)  # refuses a root too
        if target.pk == locked.parent_id and slot == locked.slot:
            return locked
        old_parent = locked.parent
        old_slot, old_path = locked.slot, _public_path(locked)
        locked.parent, locked.slot = target, slot
        _save(locked, _unique_errors(), update_fields=["parent", "slot", "updated_at"])
        locked.refresh_from_db(fields=["path"])
        record_event(
            STORAGE_UNIT_MOVED,
            Change(
                STORAGE_UNIT,
                locked.public_id,
                {
                    "parent": [_ref(old_parent), str(target.public_id)],
                    "slot": [old_slot, slot],
                    "path": [old_path, _public_path(locked)],
                },
                lab_id=locked.lab_id,
            ),
        )
    return locked


def unit_set_status(
    *, access: Access, unit: StorageUnit, status: UnitStatus, reason: str
) -> StorageUnit:
    """Out of service and back, or retired for good once it holds nothing. With a reason."""
    reason = reason.strip()
    if not reason:
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    with audited_atomic():
        lock_lab(unit.lab_id)
        _require_role(access, unit.lab_id)
        locked = _locked_unit(unit)
        old = UnitStatus(locked.status)
        if status == old:
            return locked
        if status not in NEXT_STATUS[old]:
            raise InvalidUnit("This status cannot follow the current one.", attr="status")
        if status == UnitStatus.RETIRED:
            held = StorageUnit.objects.filter(parent=locked).exclude(status=UnitStatus.RETIRED)
            if held.exists() or (locked.kind == UnitKind.BOX and box_occupied(locked)):
                raise UnitNotEmpty
            locked.retired_at = timezone.now()
        locked.status = status
        locked.save(update_fields=["status", "retired_at", "updated_at"])
        record_event(
            STORAGE_UNIT_STATUS_CHANGED,
            Change(STORAGE_UNIT, locked.public_id, {"status": [old, status]}, lab_id=locked.lab_id),
            reason=reason,
        )
    return locked


# Box types: global, changed by staff in admin (no lab, so no lab lock and no role).


def _check_box_type_name(name: str) -> str:
    name = normalised(name)
    if not name:
        raise InvalidUnit("Enter a name.", attr="name")
    return name


def box_type_create(*, name: str, rows: int, cols: int) -> BoxType:
    name = _check_box_type_name(name)
    if not 1 <= rows <= MAX_ROWS:
        raise InvalidUnit(f"A box has 1 to {MAX_ROWS} rows.", attr="rows")
    if not 1 <= cols <= MAX_COLS:
        raise InvalidUnit(f"A box has 1 to {MAX_COLS} columns.", attr="cols")
    with audited_atomic():
        box_type = BoxType(name=name, rows=rows, cols=cols)
        _save(box_type, {BOX_TYPE_NAME_UNIQUE: InvalidUnit("This name is taken.", attr="name")})
        record_event(
            BOX_TYPE_CREATED,
            Change(
                BOX_TYPE,
                box_type.public_id,
                {"name": [None, name], "rows": [None, rows], "cols": [None, cols]},
            ),
        )
    return box_type


def box_type_rename(*, box_type: BoxType, name: str) -> BoxType:
    """Only the name: the boxes made from a type keep the size they copied."""
    name = _check_box_type_name(name)
    with audited_atomic():
        locked = BoxType.objects.select_for_update().filter(pk=box_type.pk).first()
        if locked is None:
            raise NotFound
        if locked.name == name:
            return locked
        old, locked.name = locked.name, name
        _save(locked, {BOX_TYPE_NAME_UNIQUE: InvalidUnit("This name is taken.", attr="name")})
        record_event(BOX_TYPE_CHANGED, Change(BOX_TYPE, locked.public_id, {"name": [old, name]}))
    return locked
