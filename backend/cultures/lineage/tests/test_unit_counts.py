"""What a storage unit holds, in numbers (#80): the boxes below it, the vials placed in it or
below it, and the free positions of its boxes, on the storage tree and on a unit's page.

The vials come from lineage, so the tests live here. A count is no location: it includes the
vials of a regulated strain, as the box grid shows their positions as taken (ADR 0009, amendment
of 2026-10-20), and names none of them.
"""

from dataclasses import dataclass

import pytest

from cultures.audit.context import AuditContext
from cultures.core.testing import QueryBaseline, logged_in
from cultures.labs.access import Access
from cultures.lineage.models import Passage, Vial
from cultures.lineage.tests.test_masking import end_restrictions
from cultures.storage import services as storage
from cultures.storage.models import BoxType, StorageUnit, UnitKind, UnitStatus
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import LAB_URL, VIALS_URL, MakeBatch, vials_of

pytestmark = pytest.mark.django_db
UNITS_URL = f"{LAB_URL}/storage-units/"


@dataclass
class Stocked:
    """Freezer A > Rack 1 > Box 1 (9 x 9): three plain vials and two regulated ones.
    Rack 1 > Box 2 (10 x 10): one plain vial. Rack 1 > Box R: retired, empty.
    Freezer A > Box F (9 x 9) in the freezer itself: one plain vial.
    Freezer A > Rack 2: empty."""

    tree: Tree
    box2: StorageUnit
    retired: StorageUnit
    box_f: StorageUnit
    rack2: StorageUnit
    plain: list[Vial]
    hidden: list[Vial]


@pytest.fixture
def stocked(
    *,
    tree: Tree,
    make_unit: MakeUnit,
    box_10x10: BoxType,
    passage0: Passage,
    regulated: Strain,
    make_batch: MakeBatch,
    as_curator: AuditContext,
    curator_access: Access,
) -> Stocked:
    box2 = make_unit(UnitKind.BOX, "Box 2", tree.rack, slot=2, box_type=box_10x10)
    retired = make_unit(UnitKind.BOX, "Box R", tree.rack, slot=3)
    storage.unit_set_status(
        access=curator_access, unit=retired, status=UnitStatus.RETIRED, reason="cracked"
    )
    box_f = make_unit(UnitKind.BOX, "Box F", tree.freezer, slot=3)
    rack2 = make_unit(UnitKind.RACK, "Rack 2", tree.freezer, slot=2)
    plain = vials_of(make_batch(passage0, vial_count=3, box=tree.box))
    hidden = vials_of(
        make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=2, box=tree.box)
    )
    plain += vials_of(make_batch(passage0, vial_count=1, box=box2))
    plain += vials_of(make_batch(passage0, vial_count=1, box=box_f))
    return Stocked(tree, box2, retired, box_f, rack2, plain, hidden)


def counts(boxes: int, vials: int, free: int) -> dict[str, int]:
    return {"boxes": boxes, "vials": vials, "free_positions": free}


# Box 1 81 places, 5 taken; Box 2 100, 1; Box F 81, 1; Box R retired: counted nowhere.
EXPECTED = {
    "Freezer A": counts(3, 7, 81 + 100 + 81 - 7),
    "Rack 1": counts(2, 6, 81 + 100 - 6),
    "Box 1": counts(0, 5, 76),
    "Box 2": counts(0, 1, 99),
    "Box R": counts(0, 0, 0),
    "Rack 2": counts(0, 0, 0),
    "Box F": counts(0, 1, 80),
}


def tree_counts(user: User) -> dict[str, dict[str, int]]:
    response = logged_in(user).get(UNITS_URL)
    assert response.status_code == 200, response.content
    return {row["name"]: row["counts"] for row in response.json()}


def test_each_unit_of_the_tree_counts_itself_and_everything_below_it(
    viewer: User, stocked: Stocked
) -> None:
    assert tree_counts(viewer) == EXPECTED


def test_a_unit_page_counts_the_unit_and_each_unit_it_holds(viewer: User, stocked: Stocked) -> None:
    freezer = logged_in(viewer).get(f"{UNITS_URL}{stocked.tree.freezer.public_id}/").json()
    assert freezer["counts"] == EXPECTED["Freezer A"]
    assert {c["name"]: c["counts"] for c in freezer["children"]} == {
        name: EXPECTED[name] for name in ("Rack 1", "Rack 2", "Box F")
    }
    rack = logged_in(viewer).get(f"{UNITS_URL}{stocked.tree.rack.public_id}/").json()
    assert rack["counts"] == EXPECTED["Rack 1"]
    assert {c["name"]: c["counts"] for c in rack["children"]} == {
        name: EXPECTED[name] for name in ("Box 1", "Box 2", "Box R")
    }
    box = logged_in(viewer).get(f"{UNITS_URL}{stocked.tree.box.public_id}/").json()
    assert box["counts"] == EXPECTED["Box 1"]


def test_a_vial_moved_counts_only_where_it_is_now(
    technician: User, viewer: User, stocked: Stocked
) -> None:
    moved = logged_in(technician).post(
        f"{VIALS_URL}{stocked.plain[0].public_id}/place/",
        {"box": str(stocked.box_f.public_id), "row": 2, "col": 2},
        content_type="application/json",
    )
    assert moved.status_code == 200, moved.content
    now = tree_counts(viewer)
    assert (now["Box 1"], now["Box F"]) == (counts(0, 4, 77), counts(0, 2, 79))
    assert (now["Rack 1"], now["Freezer A"]) == (counts(2, 5, 176), EXPECTED["Freezer A"])


def identities(vial: Vial) -> list[str]:
    strain = vial.batch.strain
    return [
        str(vial.public_id),
        str(vial.batch.public_id),
        str(strain.public_id),
        str(strain.accession_number),
        strain.name_as_received,
        strain.taxon.name,
    ]


def test_a_regulated_vial_is_counted_but_named_nowhere(
    *, viewer: User, curator: User, stocked: Stocked, regulated: Strain
) -> None:
    pages = [UNITS_URL] + [
        f"{UNITS_URL}{unit.public_id}/"
        for unit in (stocked.tree.freezer, stocked.tree.rack, stocked.tree.box)
    ]
    for url in pages:
        text = logged_in(viewer).get(url).content.decode()
        for vial in stocked.hidden:
            for identity in identities(vial):
                assert identity not in text, (url, identity)
    # The same numbers once the strain is no longer regulated: the two vials were in them.
    end_restrictions(curator, regulated)
    assert tree_counts(viewer) == EXPECTED


def one_vial_per_box(
    units: int, *, tree: Tree, make_unit: MakeUnit, make_batch: MakeBatch, passage: Passage
) -> None:
    """`units` boxes in Rack 1, Box 1 included, each with one vial."""
    boxes = [tree.box] + [
        make_unit(UnitKind.BOX, f"Box {slot}", tree.rack, slot=slot) for slot in range(2, units + 1)
    ]
    for box in boxes:
        make_batch(passage, vial_count=1, box=box)


@pytest.mark.parametrize("boxes", [1, 20])
def test_the_tree_with_its_counts_is_a_fixed_number_of_queries(
    *,
    boxes: int,
    viewer: User,
    tree: Tree,
    make_unit: MakeUnit,
    passage0: Passage,
    make_batch: MakeBatch,
    query_baseline: QueryBaseline,
) -> None:
    one_vial_per_box(boxes, tree=tree, make_unit=make_unit, make_batch=make_batch, passage=passage0)
    client = logged_in(viewer)
    # Session, user, memberships, the lab, the tree, and the counts of every unit in one query.
    with query_baseline("unit_tree_with_vials") as captured:
        rows = client.get(UNITS_URL).json()
    assert {r["name"]: r["counts"]["vials"] for r in rows}["Freezer A"] == boxes
    counted = [q["sql"] for q in captured.captured_queries if '"lineage_vialplacement"' in q["sql"]]
    assert len(counted) == 1
    assert '"storage_storageunit"."lab_id" IN' in counted[0]


@pytest.mark.parametrize("boxes", [1, 20])
def test_a_unit_page_with_its_counts_is_a_fixed_number_of_queries(
    *,
    boxes: int,
    viewer: User,
    tree: Tree,
    make_unit: MakeUnit,
    passage0: Passage,
    make_batch: MakeBatch,
    query_baseline: QueryBaseline,
) -> None:
    one_vial_per_box(boxes, tree=tree, make_unit=make_unit, make_batch=make_batch, passage=passage0)
    client = logged_in(viewer)
    # Session, user, memberships, the lab, the unit, its breadcrumbs, what it holds, and the
    # counts of the unit and each unit it holds in one query.
    with query_baseline("unit_detail_with_vials"):
        body = client.get(f"{UNITS_URL}{tree.rack.public_id}/").json()
    assert body["counts"]["vials"] == boxes
    assert [c["counts"]["vials"] for c in body["children"]] == [1] * boxes
