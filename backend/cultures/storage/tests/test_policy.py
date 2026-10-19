"""The may_store gate of ADR 0009: only a box takes material, only while it and every unit
above it are active, and only up to the lowest risk group cap along its path."""

import pytest

from cultures.audit.context import AuditContext
from cultures.labs.access import Access
from cultures.storage import services
from cultures.storage.models import UnitKind, UnitStatus
from cultures.storage.policy import StoreDecision, decide, may_store
from cultures.storage.services import UnitFields

from .conftest import MakeUnit, Tree

pytestmark = pytest.mark.django_db

DECISIONS = [
    ("a box within its cap", "box", True, 2, 2, StoreDecision(True, cap=2)),
    ("a box below its cap", "box", True, 3, 1, StoreDecision(True, cap=3)),
    (
        "above the cap",
        "box",
        True,
        2,
        3,
        StoreDecision(False, "risk_group_above_cap", "This box takes risk group 2 at most.", 2),
    ),
    (
        "a rack",
        "rack",
        True,
        2,
        1,
        StoreDecision(False, "not_a_box", "Material is stored in boxes only.", 2),
    ),
    (
        "a freezer",
        "freezer",
        True,
        2,
        1,
        StoreDecision(False, "not_a_box", "Material is stored in boxes only.", 2),
    ),
    (
        "an inactive path",
        "box",
        False,
        2,
        1,
        StoreDecision(
            False,
            "unit_not_active",
            "The box or a unit holding it is out of service or retired.",
            2,
        ),
    ),
    (
        "no cap at all",
        "box",
        True,
        None,
        1,
        StoreDecision(False, "risk_group_above_cap", "This box has no cap.", None),
    ),
]


@pytest.mark.parametrize(
    ("kind", "active", "cap", "group", "expected"),
    [d[1:] for d in DECISIONS],
    ids=[d[0] for d in DECISIONS],
)
def test_the_rule_on_the_facts(
    kind: str, active: bool, cap: int | None, group: int, expected: StoreDecision
) -> None:
    assert decide(kind=kind, path_active=active, cap=cap, risk_group=group) == expected


def test_the_cap_is_the_lowest_along_the_path(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    """Freezer 2, rack and box without one: 2. The rack lowers it to 1: 1 for the box. The box
    raising its own to 3 changes nothing: the rack's 1 still holds."""
    assert may_store(unit=tree.box, risk_group=2).allowed
    assert not may_store(unit=tree.box, risk_group=3).allowed
    services.unit_update(
        access=curator_access, unit=tree.rack, fields=UnitFields(name="Rack 1", max_risk_group=1)
    )
    assert may_store(unit=tree.box, risk_group=2) == StoreDecision(
        False, "risk_group_above_cap", "This box takes risk group 1 at most.", 1
    )
    services.unit_update(
        access=curator_access,
        unit=tree.box,
        fields=UnitFields(name="Box 1", max_risk_group=3, box_type=tree.box.box_type),
    )
    assert may_store(unit=tree.box, risk_group=2).cap == 1


def test_the_cap_follows_a_move(
    as_curator: AuditContext, curator_access: Access, tree: Tree, make_unit: MakeUnit
) -> None:
    tank = make_unit(UnitKind.LN2_TANK, "Tank for group 3", max_risk_group=3)
    assert may_store(unit=tree.box, risk_group=3).cap == 2
    services.unit_move(access=curator_access, unit=tree.rack, parent=tank, slot=None)
    assert may_store(unit=tree.box, risk_group=3) == StoreDecision(True, cap=3)


def test_a_freezer_out_of_service_takes_nothing_also_through_its_rack(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    services.unit_set_status(
        access=curator_access, unit=tree.freezer, status=UnitStatus.OUT_OF_SERVICE, reason="alarm"
    )
    assert may_store(unit=tree.box, risk_group=1).code == "unit_not_active"
    services.unit_set_status(
        access=curator_access, unit=tree.freezer, status=UnitStatus.ACTIVE, reason="cold again"
    )
    assert may_store(unit=tree.box, risk_group=1).allowed


def test_a_retired_box_takes_nothing(
    as_curator: AuditContext, curator_access: Access, tree: Tree
) -> None:
    services.unit_set_status(
        access=curator_access, unit=tree.box, status=UnitStatus.RETIRED, reason="cracked"
    )
    assert may_store(unit=tree.box, risk_group=1).code == "unit_not_active"
