"""Every public unit service of cultures.storage takes the lab lock first.

Each one has a scenario here, run with the SQL captured, or a reviewed exemption. The
captured SQL must show the lab row locked (SELECT ... FROM "labs_lab" ... FOR UPDATE) before
the service reads the actor's role (labs_membership), reads or locks a unit, and writes to
a storage table. A new service fails until someone puts it on one side. SQL is text: the
thread race in test_concurrency.py proves what PostgreSQL does with the tree lock.
"""

from collections.abc import Callable
from functools import partial

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext
from cultures.labs.access import Access, access_for
from cultures.labs.tests.test_lock_invariant import first, locks, public_services
from cultures.storage import services
from cultures.storage.models import BoxType, UnitKind, UnitStatus
from cultures.storage.services import NewUnit, UnitFields
from cultures.users.models import User

from .conftest import MakeUnit, Tree

pytestmark = pytest.mark.django_db

Scenario = Callable[[Access, Tree, BoxType, MakeUnit], Callable[[], object]]

SCENARIOS: dict[str, Scenario] = {
    "unit_create": lambda a, t, bt, make: (
        lambda: services.unit_create(
            access=a,
            lab=t.freezer.lab,
            data=NewUnit(kind=UnitKind.BOX, name="Box 2", parent=t.rack, box_type=bt),
        )
    ),
    "unit_update": lambda a, t, bt, make: (
        lambda: services.unit_update(
            access=a, unit=t.box, fields=UnitFields(name="Box 2", box_type=bt)
        )
    ),
    "unit_move": lambda a, t, bt, make: partial(
        services.unit_move, access=a, unit=t.rack, parent=make(UnitKind.LN2_TANK, "Tank"), slot=None
    ),
    "unit_set_status": lambda a, t, bt, make: (
        lambda: services.unit_set_status(
            access=a, unit=t.box, status=UnitStatus.RETIRED, reason="r"
        )
    ),
}

EXEMPT: dict[str, str] = {
    "box_type_create": "a global box type: no lab to lock, staff only, in admin",
    "box_type_rename": "a global box type: no lab to lock, staff only, in admin",
    "box_occupied": "a read the services call under their lock",
    "held_risk_group": "a read the services call under their lock",
    "normalised": "text normalisation, no query",
}


def test_every_public_service_has_a_scenario_or_a_reviewed_exemption() -> None:
    found = public_services(services)
    assert len(found) >= len(SCENARIOS)  # the walk found the services
    assert sorted(found - set(SCENARIOS) - set(EXEMPT)) == []
    assert sorted((set(SCENARIOS) | set(EXEMPT)) - found) == []


def reads(table: str) -> Callable[[str], bool]:
    return lambda sql: sql.startswith("SELECT") and f'FROM "{table}"' in sql


def writes(sql: str) -> bool:
    return sql.startswith(("INSERT INTO", "UPDATE")) and '"storage_' in sql.split("(", 1)[0]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_lab_lock_comes_first(
    *,
    name: str,
    curator: User,
    tree: Tree,
    box_10x10: BoxType,
    make_unit: MakeUnit,
    as_curator: AuditContext,
) -> None:
    # The access object is built before the capture: the request does that before the service.
    call = SCENARIOS[name](access_for(curator), tree, box_10x10, make_unit)
    with CaptureQueriesContext(connection) as captured:
        call()
    statements = [q["sql"] for q in captured.captured_queries]
    lock = first(statements, locks("labs_lab"))
    assert lock is not None, f"{name} never locks the lab:\n" + "\n".join(statements)
    for match in (reads("labs_membership"), reads("storage_storageunit"), writes):
        found = first(statements, match)
        assert found is None or found > lock, (
            f"{name}: statement {found} before the lab lock {lock}"
        )
    assert first(statements, writes) is not None, f"{name} writes nothing"
    unit_lock = first(statements, locks("storage_storageunit"))
    assert name == "unit_create" or (unit_lock is not None and unit_lock > lock), (
        f"{name} changes a unit it never locked"
    )
