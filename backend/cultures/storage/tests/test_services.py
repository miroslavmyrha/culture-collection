"""The storage services: what each records, what each refuses, and that a refusal changes
nothing and records nothing."""

from collections.abc import Callable
from typing import Any

import pytest

from cultures.audit.context import AuditContext, MissingAuditContext, audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.test_lock_invariant import public_services
from cultures.storage import services
from cultures.storage.models import BoxType, StorageUnit, UnitKind, UnitStatus
from cultures.storage.services import NewUnit, UnitFields
from cultures.users.models import User

from .conftest import MakeUnit, Tree, fresh

pytestmark = pytest.mark.django_db


def snapshot() -> tuple[Any, ...]:
    rows = tuple(list(m._default_manager.order_by("pk").values()) for m in (StorageUnit, BoxType))
    return (*rows, AuditEvent.objects.count())


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> DomainError:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before
    return raised.value


def create(access: Access, lab: Lab, kind: UnitKind, name: str, **fields: Any) -> StorageUnit:
    return services.unit_create(
        access=access, lab=lab, data=NewUnit(kind=kind, name=name, **fields)
    )


def last_event() -> AuditEvent:
    return AuditEvent.objects.order_by("-pk").first()  # type: ignore[return-value]


# Adding units.


def test_a_curator_builds_freezer_rack_and_box_and_each_is_one_event(
    as_curator: AuditContext, curator: User, curator_access: Access, lab: Lab, box_9x9: BoxType
) -> None:
    freezer = create(
        curator_access, lab, UnitKind.FREEZER, "  Freezer   A ", temperature_c=-80, max_risk_group=2
    )
    rack = create(curator_access, lab, UnitKind.RACK, "Rack 1", parent=freezer, slot=3)
    box = create(
        curator_access,
        lab,
        UnitKind.BOX,
        "Box 1",
        parent=rack,
        slot=1,
        barcode=" BX-1 ",
        box_type=box_9x9,
    )
    assert freezer.name == "Freezer A"
    assert (box.rows, box.cols, box.barcode) == (9, 9, "BX-1")
    assert list(box.path) == [freezer.pk, rack.pk, box.pk]
    events = list(AuditEvent.objects.filter(subject_type="storage_unit").order_by("pk"))
    assert [e.event_type for e in events] == ["storage_unit_created"] * 3
    event = events[2]
    assert (event.actor, event.lab_id, event.subject_type, event.subject_id) == (
        curator,
        lab.pk,
        "storage_unit",
        box.public_id,
    )
    assert event.strain_id is None  # units hold no strain
    assert event.changes == {
        "kind": [None, "box"],
        "name": [None, "Box 1"],
        "parent": [None, str(rack.public_id)],
        "slot": [None, 1],
        "status": [None, "active"],
        "barcode": [None, "BX-1"],
        "temperature_c": [None, None],
        "max_risk_group": [None, None],
        "box_type": [None, str(box_9x9.public_id)],
        "rows": [None, 9],
        "cols": [None, 9],
    }


def test_a_box_copies_its_size_and_keeps_it_when_the_type_is_renamed(
    tree: Tree, box_9x9: BoxType
) -> None:
    with audit_context(channel=Channel.WEB, actor_kind=ActorKind.SYSTEM, actor_label="command:t"):
        services.box_type_rename(box_type=box_9x9, name="Old 81-place box")
    assert (fresh(tree.box).rows, fresh(tree.box).cols) == (9, 9)
    assert last_event().changes == {"name": ["Cryobox 9 x 9", "Old 81-place box"]}


KIND_REFUSALS = [
    ("a box holds no freezer", UnitKind.FREEZER, "box", "invalid", "parent"),
    ("a box holds no rack", UnitKind.RACK, "box", "kind_not_allowed", "parent"),
    ("a box holds no box", UnitKind.BOX, "box", "kind_not_allowed", "parent"),
    ("a rack holds no rack", UnitKind.RACK, "rack", "kind_not_allowed", "parent"),
    ("a freezer stands alone", UnitKind.LN2_TANK, "freezer", "invalid", "parent"),
]


@pytest.mark.parametrize(
    ("kind", "parent", "code", "attr"),
    [c[1:] for c in KIND_REFUSALS],
    ids=[c[0] for c in KIND_REFUSALS],
)
def test_the_kind_spec_is_the_services_too(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    tree: Tree,
    box_9x9: BoxType,
    kind: UnitKind,
    parent: str,
    code: str,
    attr: str,
) -> None:
    holder = getattr(tree, parent)
    extra = {"box_type": box_9x9} if kind == UnitKind.BOX else {"max_risk_group": 2}
    refused(
        services.InvalidUnit,
        code,
        lambda: create(curator_access, lab, kind, "new", parent=holder, **extra),
        attr,
    )


Fields = Callable[[Tree, BoxType], dict[str, Any]]
INPUT_REFUSALS: list[tuple[str, UnitKind, Fields, str]] = [
    ("no name", UnitKind.FREEZER, lambda t, bt: {"name": "   ", "max_risk_group": 2}, "name"),
    ("a root without a cap", UnitKind.FREEZER, lambda t, bt: {}, "max_risk_group"),
    ("a cap of 5", UnitKind.FREEZER, lambda t, bt: {"max_risk_group": 5}, "max_risk_group"),
    (
        "too cold",
        UnitKind.FREEZER,
        lambda t, bt: {"max_risk_group": 2, "temperature_c": -274},
        "temperature_c",
    ),
    (
        "a barcode with a space",
        UnitKind.FREEZER,
        lambda t, bt: {"max_risk_group": 2, "barcode": "A B"},
        "barcode",
    ),
    ("a slot on a root", UnitKind.FREEZER, lambda t, bt: {"max_risk_group": 2, "slot": 1}, "slot"),
    (
        "a box type on a freezer",
        UnitKind.FREEZER,
        lambda t, bt: {"max_risk_group": 2, "box_type": bt},
        "box_type",
    ),
    ("a rack without a parent", UnitKind.RACK, lambda t, bt: {}, "parent"),
    ("a box without a type", UnitKind.BOX, lambda t, bt: {"parent": t.rack}, "box_type"),
    ("slot 0", UnitKind.BOX, lambda t, bt: {"parent": t.rack, "box_type": bt, "slot": 0}, "slot"),
]


@pytest.mark.parametrize(
    ("kind", "fields", "attr"), [c[1:] for c in INPUT_REFUSALS], ids=[c[0] for c in INPUT_REFUSALS]
)
def test_invalid_input_is_a_field_error(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    tree: Tree,
    box_9x9: BoxType,
    kind: UnitKind,
    fields: Fields,
    attr: str,
) -> None:
    values = {"name": "new", **fields(tree, box_9x9)}
    name = values.pop("name")
    refused(
        services.InvalidUnit,
        "invalid",
        lambda: create(curator_access, lab, kind, name, **values),
        attr,
    )


def test_a_parent_of_another_lab_reads_like_an_unknown_one(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    other_lab: Lab,
    make_unit: MakeUnit,
    outsider: User,
) -> None:
    elsewhere = make_unit(UnitKind.FREEZER, "Freezer B", lab=other_lab, actor=outsider)
    error = refused(
        services.InvalidUnit,
        "does_not_exist",
        lambda: create(curator_access, lab, UnitKind.RACK, "Rack", parent=elsewhere),
        "parent",
    )
    assert error.detail == "Invalid storage unit."


@pytest.mark.parametrize("status", [UnitStatus.OUT_OF_SERVICE, UnitStatus.RETIRED])
def test_nothing_goes_into_a_unit_out_of_service_or_retired(
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    make_unit: MakeUnit,
    status: UnitStatus,
) -> None:
    freezer = make_unit(UnitKind.FREEZER, "Old freezer")
    services.unit_set_status(access=curator_access, unit=freezer, status=status, reason="broken")
    refused(
        services.InvalidUnit,
        "parent_not_active",
        lambda: create(curator_access, lab, UnitKind.RACK, "Rack", parent=freezer),
        "parent",
    )


TAKEN = [
    ("name", {"name": "box 1"}),
    ("slot", {"name": "Box 2", "slot": 1}),
    ("barcode", {"name": "Box 2", "barcode": "BX-1"}),
]


@pytest.mark.parametrize(("attr", "fields"), TAKEN, ids=[a for a, _ in TAKEN])
def test_a_name_slot_or_barcode_taken_is_a_field_error(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    tree: Tree,
    box_9x9: BoxType,
    make_unit: MakeUnit,
    attr: str,
    fields: dict[str, Any],
) -> None:
    make_unit(UnitKind.FREEZER, "Barcoded", barcode="BX-1")
    values = dict(fields)
    name = values.pop("name")
    refused(
        services.InvalidUnit,
        "unique",
        lambda: create(
            curator_access, lab, UnitKind.BOX, name, parent=tree.rack, box_type=box_9x9, **values
        ),
        attr,
    )


# Changing a unit.


def test_a_change_records_only_what_changed_and_nothing_changed_records_nothing(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    before = AuditEvent.objects.count()
    services.unit_update(
        access=curator_access,
        unit=tree.freezer,
        fields=UnitFields(name="Freezer A", temperature_c=-80, max_risk_group=2),
    )
    assert AuditEvent.objects.count() == before
    services.unit_update(
        access=curator_access,
        unit=tree.freezer,
        fields=UnitFields(
            name="Freezer A (lab 2.14)", barcode="FRZ-A", temperature_c=-86, max_risk_group=1
        ),
    )
    event = last_event()
    assert event.event_type == "storage_unit_changed"
    assert event.changes == {
        "name": ["Freezer A", "Freezer A (lab 2.14)"],
        "barcode": [None, "FRZ-A"],
        "temperature_c": [-80, -86],
        "max_risk_group": [2, 1],
    }


def test_a_box_takes_a_new_type_and_its_size_while_nothing_occupies_it(
    as_curator: AuditContext, curator_access: Access, tree: Tree, box_10x10: BoxType
) -> None:
    services.unit_update(
        access=curator_access, unit=tree.box, fields=UnitFields(name="Box 1", box_type=box_10x10)
    )
    box = fresh(tree.box)
    assert (box.box_type_id, box.rows, box.cols) == (box_10x10.pk, 10, 10)
    assert last_event().changes["rows"] == [9, 10]


def test_an_occupied_box_keeps_its_size(
    as_curator: AuditContext,
    curator_access: Access,
    tree: Tree,
    box_10x10: BoxType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hook #16 fills with its placements: an occupied box refuses a new size."""
    asked: list[StorageUnit] = []

    def occupied(box: StorageUnit) -> bool:
        asked.append(box)
        return True

    monkeypatch.setattr(services, "box_occupied", occupied)
    refused(
        services.BoxOccupied,
        "box_occupied",
        lambda: services.unit_update(
            access=curator_access,
            unit=tree.box,
            fields=UnitFields(name="Box 1", box_type=box_10x10),
        ),
        "box_type",
    )
    assert [b.pk for b in asked] == [tree.box.pk]
    # Its name still changes: only the size is frozen.
    services.unit_update(
        access=curator_access,
        unit=tree.box,
        fields=UnitFields(name="Box 1a", box_type=tree.box.box_type),
    )
    assert fresh(tree.box).name == "Box 1a"


def test_no_position_is_occupied_before_vials_exist(tree: Tree) -> None:
    assert services.box_occupied(tree.box) is False


def test_a_root_keeps_its_cap(as_curator: AuditContext, curator_access: Access, tree: Tree) -> None:
    refused(
        services.InvalidUnit,
        "invalid",
        lambda: services.unit_update(
            access=curator_access, unit=tree.freezer, fields=UnitFields(name="Freezer A")
        ),
        "max_risk_group",
    )


# Moving a unit.


def test_a_move_takes_everything_below_and_records_both_paths(
    as_curator: AuditContext, curator_access: Access, tree: Tree, make_unit: MakeUnit
) -> None:
    tank = make_unit(UnitKind.LN2_TANK, "Tank B")
    services.unit_move(access=curator_access, unit=tree.rack, parent=tank, slot=4)
    assert list(fresh(tree.box).path) == [tank.pk, tree.rack.pk, tree.box.pk]
    event = last_event()
    assert (event.event_type, event.subject_id, event.lab_id) == (
        "storage_unit_moved",
        tree.rack.public_id,
        tree.rack.lab_id,
    )
    assert event.changes == {
        "parent": [str(tree.freezer.public_id), str(tank.public_id)],
        "slot": [1, 4],
        "path": [
            [str(tree.freezer.public_id), str(tree.rack.public_id)],
            [str(tank.public_id), str(tree.rack.public_id)],
        ],
    }


def test_a_move_to_the_same_place_records_nothing(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    before = snapshot()
    services.unit_move(access=curator_access, unit=tree.box, parent=tree.rack, slot=1)
    assert snapshot() == before


def test_a_move_inside_itself_is_refused_on_the_parent(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    for target in (tree.rack, tree.box):
        refused(
            services.InvalidUnit,
            "cycle",
            lambda target=target: services.unit_move(  # type: ignore[misc]
                access=curator_access, unit=tree.rack, parent=target, slot=None
            ),
            "parent",
        )


def test_a_freezer_is_never_moved_into_anything(
    as_curator: AuditContext, curator_access: Access, tree: Tree, make_unit: MakeUnit
) -> None:
    tank = make_unit(UnitKind.LN2_TANK, "Tank B")
    refused(
        services.InvalidUnit,
        "invalid",
        lambda: services.unit_move(
            access=curator_access, unit=tree.freezer, parent=tank, slot=None
        ),
        "parent",
    )


def test_a_box_cannot_go_into_a_box(
    as_curator: AuditContext, curator_access: Access, tree: Tree, make_unit: MakeUnit
) -> None:
    other = make_unit(UnitKind.BOX, "Box 2", tree.rack)
    refused(
        services.InvalidUnit,
        "kind_not_allowed",
        lambda: services.unit_move(access=curator_access, unit=tree.box, parent=other, slot=None),
        "parent",
    )


def test_a_move_into_a_taken_slot_is_a_field_error(
    as_curator: AuditContext, curator_access: Access, tree: Tree, make_unit: MakeUnit
) -> None:
    other = make_unit(UnitKind.BOX, "Box 2", tree.rack, slot=2)
    refused(
        services.InvalidUnit,
        "unique",
        lambda: services.unit_move(access=curator_access, unit=other, parent=tree.rack, slot=1),
        "slot",
    )


# Status.


def test_out_of_service_and_back_each_with_a_reason(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    services.unit_set_status(
        access=curator_access,
        unit=tree.freezer,
        status=UnitStatus.OUT_OF_SERVICE,
        reason="defrosting",
    )
    event = last_event()
    assert (event.event_type, event.changes, event.reason) == (
        "storage_unit_status_changed",
        {"status": ["active", "out_of_service"]},
        "defrosting",
    )
    services.unit_set_status(
        access=curator_access, unit=tree.freezer, status=UnitStatus.ACTIVE, reason="cold again"
    )
    assert fresh(tree.freezer).status == UnitStatus.ACTIVE


def test_a_status_change_needs_a_reason(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.unit_set_status(
            access=curator_access, unit=tree.box, status=UnitStatus.RETIRED, reason="  "
        ),
        "reason",
    )


def test_a_unit_is_retired_only_once_it_holds_nothing(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    refused(
        services.UnitNotEmpty,
        "unit_not_empty",
        lambda: services.unit_set_status(
            access=curator_access, unit=tree.rack, status=UnitStatus.RETIRED, reason="old"
        ),
    )
    services.unit_set_status(
        access=curator_access, unit=tree.box, status=UnitStatus.RETIRED, reason="cracked"
    )
    services.unit_set_status(
        access=curator_access, unit=tree.rack, status=UnitStatus.RETIRED, reason="old"
    )
    rack = fresh(tree.rack)
    assert (rack.status, rack.retired_at is not None) == (UnitStatus.RETIRED, True)


def test_an_occupied_box_is_not_retired(
    as_curator: AuditContext, curator_access: Access, tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "box_occupied", lambda box: True)
    refused(
        services.UnitNotEmpty,
        "unit_not_empty",
        lambda: services.unit_set_status(
            access=curator_access, unit=tree.box, status=UnitStatus.RETIRED, reason="cracked"
        ),
    )


RETIRED_REFUSALS: list[tuple[str, Callable[[Access, Tree], object]]] = [
    (
        "status",
        lambda a, t: services.unit_set_status(
            access=a, unit=t.box, status=UnitStatus.ACTIVE, reason="r"
        ),
    ),
    (
        "change",
        lambda a, t: services.unit_update(
            access=a, unit=t.box, fields=UnitFields(name="x", box_type=t.box.box_type)
        ),
    ),
    ("move", lambda a, t: services.unit_move(access=a, unit=t.box, parent=t.freezer, slot=None)),
]


@pytest.mark.parametrize(
    "call", [c for _, c in RETIRED_REFUSALS], ids=[n for n, _ in RETIRED_REFUSALS]
)
def test_a_retired_unit_changes_no_more(
    as_curator: AuditContext,
    curator_access: Access,
    tree: Tree,
    call: Callable[[Access, Tree], object],
) -> None:
    services.unit_set_status(
        access=curator_access, unit=tree.box, status=UnitStatus.RETIRED, reason="cracked"
    )
    refused(services.UnitRetired, "unit_retired", lambda: call(curator_access, tree))


def test_the_same_status_again_records_nothing(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    before = snapshot()
    services.unit_set_status(
        access=curator_access, unit=tree.box, status=UnitStatus.ACTIVE, reason="r"
    )
    assert snapshot() == before


# Who may: the role as committed now, not as the request began.

SCENARIOS: dict[str, Callable[[Access, Lab, Tree, BoxType], object]] = {
    "unit_create": lambda a, lab, t, bt: create(
        a, lab, UnitKind.BOX, "Box 9", parent=t.rack, box_type=bt
    ),
    "unit_update": lambda a, lab, t, bt: services.unit_update(
        access=a, unit=t.box, fields=UnitFields(name="Box 9", box_type=bt)
    ),
    "unit_move": lambda a, lab, t, bt: services.unit_move(
        access=a, unit=t.box, parent=t.freezer, slot=None
    ),
    "unit_set_status": lambda a, lab, t, bt: services.unit_set_status(
        access=a, unit=t.box, status=UnitStatus.OUT_OF_SERVICE, reason="r"
    ),
}
# Box types are global and changed by staff in admin, without a lab or a role.
NO_LAB = {"box_type_create", "box_type_rename", "box_occupied", "normalised"}


def test_every_unit_service_has_a_scenario_here() -> None:
    found = public_services(services)
    assert {"unit_create", "unit_move"} <= found  # the walk found the services
    assert found - NO_LAB == set(SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a_curator_demoted_since_the_request_began_is_refused(
    *, name: str, as_curator: AuditContext, curator: User, lab: Lab, tree: Tree, box_9x9: BoxType
) -> None:
    access = access_for(curator)  # built while the curator was one
    Membership.objects.filter(user=curator, lab=lab).update(role=Role.TECHNICIAN)
    refused(Forbidden, "permission_denied", lambda: SCENARIOS[name](access, lab, tree, box_9x9))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a_technician_may_not_build_storage(
    name: str, technician: User, lab: Lab, tree: Tree, box_9x9: BoxType
) -> None:
    with audit_context(channel=Channel.API, actor=technician):
        refused(
            Forbidden,
            "permission_denied",
            lambda: SCENARIOS[name](access_for(technician), lab, tree, box_9x9),
        )


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_unit_service_needs_an_audit_context(
    name: str, curator_access: Access, lab: Lab, tree: Tree, box_9x9: BoxType
) -> None:
    before = snapshot()
    with pytest.raises(MissingAuditContext):
        SCENARIOS[name](curator_access, lab, tree, box_9x9)
    assert snapshot() == before


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_event_of_a_unit_service_names_the_lab_and_no_strain(
    *,
    name: str,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    tree: Tree,
    box_10x10: BoxType,
) -> None:
    before = AuditEvent.objects.count()
    SCENARIOS[name](curator_access, lab, tree, box_10x10)
    events = list(AuditEvent.objects.order_by("pk")[before:])
    assert [(e.lab_id, e.strain_id, e.subject_type) for e in events] == [
        (lab.pk, None, "storage_unit")
    ]


# Box types.


def test_box_types_have_a_name_and_a_size(box_9x9: BoxType) -> None:
    event = last_event()
    assert (event.event_type, event.lab_id, event.changes) == (
        "box_type_created",
        None,
        {"name": [None, "Cryobox 9 x 9"], "rows": [None, 9], "cols": [None, 9]},
    )
    with audit_context(channel=Channel.WEB, actor_kind=ActorKind.SYSTEM, actor_label="command:t"):
        for rows, cols, attr in ((0, 9, "rows"), (27, 9, "rows"), (9, 0, "cols"), (9, 27, "cols")):
            refused(
                services.InvalidUnit,
                "invalid",
                lambda r=rows, c=cols: services.box_type_create(name="other", rows=r, cols=c),  # type: ignore[misc]
                attr,
            )
        refused(
            services.InvalidUnit,
            "invalid",
            lambda: services.box_type_create(name="cryobox 9 X 9", rows=9, cols=9),
            "name",
        )
