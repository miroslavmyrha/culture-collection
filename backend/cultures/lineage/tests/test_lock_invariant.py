"""Every public write of cultures.lineage takes the lab lock first.

Each one has a scenario here, run with the SQL captured, or a reviewed exemption. The
captured SQL must show the lab row locked (SELECT ... FROM "labs_lab" ... FOR UPDATE) before
the service reads the actor's role (labs_membership), the strain, a vial, a box or a
placement, reads the location grant, and writes to a lineage table. A placement must lock the
box after the vial (lock order: lab, strain, vial, box). A new service fails until someone
puts it on one side. SQL is text: test_concurrency.py proves what PostgreSQL does.
"""

from collections.abc import Callable

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext
from cultures.labs.access import Access, access_for
from cultures.labs.tests.test_lock_invariant import first, locks, public_services
from cultures.lineage import services
from cultures.lineage.models import Passage, Vial, VialStatus
from cultures.storage.tests.conftest import Tree
from cultures.users.models import User

from .support import MakeBatch, new_batch, vials_of

pytestmark = pytest.mark.django_db

Scenario = Callable[[Access, Passage, Vial, Tree], Callable[[], object]]

SCENARIOS: dict[str, Scenario] = {
    "batch_preserve": lambda a, p, v, t: (
        lambda: services.batch_preserve(access=a, passage=p, data=new_batch(box=t.box))
    ),
    "passage_subculture": lambda a, p, v, t: (
        lambda: services.passage_subculture(access=a, parent=p)
    ),
    "vial_revive": lambda a, p, v, t: lambda: services.vial_revive(access=a, vial=v),
    "vial_place": lambda a, p, v, t: (
        lambda: services.vial_place(access=a, vial=v, box=t.box, row=9, col=9)
    ),
    "vial_transition": lambda a, p, v, t: (
        lambda: services.vial_transition(access=a, vial=v, status=VialStatus.LOST, reason="r")
    ),
    "vial_set_barcode": lambda a, p, v, t: (
        lambda: services.vial_set_barcode(access=a, vial=v, barcode="T-1")
    ),
    "vial_reveal_location": lambda a, p, v, t: (
        lambda: services.vial_reveal_location(access=a, vial=v)
    ),
}

EXEMPT: dict[str, str] = {
    "is_regulated": "a read the reveal calls under its lock",
    "location_of": "a read the reveal calls after its commit, and the masked lists never",
    "normalised": "text normalisation, no query",
    "position_label": "a label from two numbers, no query",
}
# Services that write nothing to a lineage table (the reveal writes only its event).
NO_LINEAGE_WRITE = {"vial_reveal_location"}


def test_every_public_service_has_a_scenario_or_a_reviewed_exemption() -> None:
    found = public_services(services)
    assert len(found) >= len(SCENARIOS)  # the walk found the services
    assert sorted(found - set(SCENARIOS) - set(EXEMPT)) == []
    assert sorted((set(SCENARIOS) | set(EXEMPT)) - found) == []


def reads(table: str) -> Callable[[str], bool]:
    return lambda sql: sql.startswith("SELECT") and f'FROM "{table}"' in sql


def writes(sql: str) -> bool:
    return sql.startswith(("INSERT INTO", "UPDATE")) and '"lineage_' in sql.split("(", 1)[0]


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_lab_lock_comes_first(
    *,
    name: str,
    technician: User,
    passage0: Passage,
    make_batch: MakeBatch,
    tree: Tree,
    as_technician: AuditContext,
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1, box=tree.box))[0]
    # The access object and the vial are loaded before the capture: the request does that.
    call = SCENARIOS[name](access_for(technician), passage0, vial, tree)
    with CaptureQueriesContext(connection) as captured:
        call()
    statements = [q["sql"] for q in captured.captured_queries]
    lock = first(statements, locks("labs_lab"))
    assert lock is not None, f"{name} never locks the lab:\n" + "\n".join(statements)
    for match in (
        reads("labs_membership"),
        reads("labs_locationgrant"),
        reads("strains_strain"),
        reads("lineage_vial"),
        reads("lineage_vialplacement"),
        reads("storage_storageunit"),
        writes,
    ):
        found = first(statements, match)
        assert found is None or found > lock, f"{name}: statement {found} before the lab lock"
    assert (first(statements, writes) is None) == (name in NO_LINEAGE_WRITE), name
    vial_lock, box_lock = (
        first(statements, locks("lineage_vial")),
        first(statements, locks("storage_storageunit")),
    )
    if vial_lock is not None and box_lock is not None:
        assert vial_lock < box_lock, f"{name} locks the box before the vial"
    if name in ("vial_place", "vial_transition", "vial_set_barcode", "vial_revive"):
        assert vial_lock is not None, f"{name} changes a vial it never locked"
    if name in ("vial_place", "batch_preserve"):
        assert box_lock is not None, f"{name} fills a box it never locked"
