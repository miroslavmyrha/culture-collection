"""The box grid API (#15): the boxes of a lab and what each position holds, for every role.

- Viewers and up read a box with its taken positions; outsiders get 404, anonymous 401.
- A position of a regulated strain's vial says `masked` and names no vial, no strain and no
  label, for every role, a holder of the location grant too (ADR 0009).
- The positions of a box come in one query, whatever their number.
- The vial list finds a vial by what the bench scans or types: its barcode or its label.
"""

import json
from typing import Any

import pytest

from cultures.core.testing import QueryBaseline, ViewsetContract, assert_problem, logged_in
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.lineage.api.views import BoxViewSet
from cultures.lineage.models import Passage, Vial
from cultures.lineage.tests.test_masking import end_restrictions, grant
from cultures.storage.models import StorageUnit, UnitKind
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import LAB_URL, VIALS_URL, MakeBatch, vials_of

pytestmark = pytest.mark.django_db
BOXES_URL = f"{LAB_URL}/boxes/"
ROLES = [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER]


class TestBoxContract(ViewsetContract):
    viewset = BoxViewSet
    url = BOXES_URL

    # Under a lab the outsider is not a member of: the whole list is a 404.
    def test_list_is_scoped(self, obj: Any, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()["results"]
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")

    @pytest.fixture
    def obj(self, tree: Tree) -> StorageUnit:
        return tree.box

    @pytest.fixture
    def reader(self, viewer: User) -> User:
        return viewer

    @pytest.fixture
    def writer(self, technician: User) -> User:
        return technician


@pytest.fixture
def mixed(
    tree: Tree, passage0: Passage, regulated: Strain, make_batch: MakeBatch
) -> tuple[list[Vial], list[Vial]]:
    """Box 1 holds two plain vials (A1, A2) and then two of the regulated strain (A3, A4)."""
    plain = vials_of(make_batch(passage0, vial_count=2, box=tree.box))
    hidden = vials_of(
        make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=2, box=tree.box)
    )
    return plain, hidden


def identities(vial: Vial) -> list[str]:
    """Everything that would tell which vial or strain it is."""
    strain = vial.batch.strain
    return [
        str(vial.public_id),
        str(vial.batch.public_id),
        str(strain.public_id),
        str(strain.accession_number),
        strain.name_as_received,
        f"{strain.accession_number} / {vial.batch.number} / {vial.seq}",
    ]


@pytest.mark.parametrize("granted", [False, True], ids=["without", "with the grant"])
@pytest.mark.parametrize("role", ROLES)
def test_a_regulated_position_is_taken_but_names_nothing(
    *,
    role: Role,
    granted: bool,
    team: dict[Role, User],
    manager: User,
    lab: Lab,
    tree: Tree,
    mixed: tuple[list[Vial], list[Vial]],
) -> None:
    plain, hidden = mixed
    reader = team[role]
    if granted:
        grant(lab, manager, reader)
    response = logged_in(reader).get(f"{BOXES_URL}{tree.box.public_id}/")
    assert response.status_code == 200, response.content
    text = response.content.decode()
    for vial in hidden:
        for identity in identities(vial):
            assert identity not in text, identity
    body = response.json()
    assert (body["public_id"], body["name"], body["rows"], body["cols"]) == (
        str(tree.box.public_id),
        "Box 1",
        9,
        9,
    )
    positions = body["positions"]
    assert [p["label"] for p in positions] == ["A1", "A2", "A3", "A4"]
    assert positions[2] == {"row": 1, "col": 3, "label": "A3", "masked": True, "vial": None}
    assert positions[3] == {"row": 1, "col": 4, "label": "A4", "masked": True, "vial": None}
    first = plain[0]
    assert positions[0] == {
        "row": 1,
        "col": 1,
        "label": "A1",
        "masked": False,
        "vial": {
            "public_id": str(first.public_id),
            "label": f"{first.batch.strain.accession_number} / {first.batch.number} / 1",
            "status": "available",
            "barcode": None,
            "strain": str(first.batch.strain.public_id),
            "accession_number": first.batch.strain.accession_number,
        },
    }


def test_a_strain_whose_restrictions_ended_shows_its_vials(
    *,
    viewer: User,
    curator: User,
    tree: Tree,
    mixed: tuple[list[Vial], list[Vial]],
    regulated: Strain,
) -> None:
    """The one definition of regulated (strains.selectors.regulating_restrictions)."""
    url = f"{BOXES_URL}{tree.box.public_id}/"
    assert [p["masked"] for p in logged_in(viewer).get(url).json()["positions"]] == [
        False,
        False,
        True,
        True,
    ]
    end_restrictions(curator, regulated)
    shown = logged_in(viewer).get(url).json()["positions"]
    assert [p["masked"] for p in shown] == [False, False, False, False]
    assert shown[2]["vial"]["public_id"] == str(mixed[1][0].public_id)


def test_only_open_placements_count(
    *, technician: User, viewer: User, tree: Tree, passage0: Passage, make_batch: MakeBatch
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1, box=tree.box))[0]
    moved = logged_in(technician).post(
        f"{VIALS_URL}{vial.public_id}/place/",
        {"box": str(tree.box.public_id), "row": 3, "col": 4},
        content_type="application/json",
    )
    assert moved.status_code == 200, moved.content
    positions = logged_in(viewer).get(f"{BOXES_URL}{tree.box.public_id}/").json()["positions"]
    assert [(p["label"], p["vial"]["public_id"]) for p in positions] == [
        ("C4", str(vial.public_id))
    ]


def test_an_empty_box_has_no_positions(viewer: User, tree: Tree) -> None:
    body = logged_in(viewer).get(f"{BOXES_URL}{tree.box.public_id}/").json()
    assert body["positions"] == []


def test_the_list_has_the_boxes_of_the_lab_only(
    viewer: User, tree: Tree, make_unit: MakeUnit
) -> None:
    second = make_unit(UnitKind.BOX, "Box 2", tree.rack, slot=2)
    listed = logged_in(viewer).get(BOXES_URL).json()
    assert [row["public_id"] for row in listed["results"]] == [
        str(tree.box.public_id),
        str(second.public_id),
    ]
    assert listed["results"][0] == {
        "public_id": str(tree.box.public_id),
        "name": "Box 1",
        "rows": 9,
        "cols": 9,
    }


@pytest.mark.parametrize("unit", ["freezer", "rack"])
def test_a_unit_that_is_no_box_is_not_found_here(viewer: User, tree: Tree, unit: str) -> None:
    target = getattr(tree, unit)
    assert_problem(logged_in(viewer).get(f"{BOXES_URL}{target.public_id}/"), 404, "not_found")


@pytest.mark.parametrize("role", ROLES)
def test_every_role_reads_and_nobody_writes_here(
    role: Role, team: dict[Role, User], tree: Tree
) -> None:
    client = logged_in(team[role])
    url = f"{BOXES_URL}{tree.box.public_id}/"
    assert client.get(url).status_code == 200
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(url, {}, content_type="application/json")
        assert_problem(response, 405, "method_not_allowed")


@pytest.mark.parametrize("vials", [1, 20])
def test_the_grid_is_one_query_whatever_it_holds(
    *,
    vials: int,
    viewer: User,
    tree: Tree,
    passage0: Passage,
    regulated: Strain,
    make_batch: MakeBatch,
    query_baseline: QueryBaseline,
) -> None:
    make_batch(passage0, vial_count=vials, box=tree.box)
    make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=1, box=tree.box)
    client = logged_in(viewer)
    # Session, user, memberships, the lab, the box, and the positions with their vials,
    # batches and strains and whether each is regulated.
    with query_baseline("box_grid") as captured:
        response = client.get(f"{BOXES_URL}{tree.box.public_id}/")
    assert len(response.json()["positions"]) == vials + 1
    grid = [q for q in captured.captured_queries if 'FROM "lineage_vialplacement"' in q["sql"]]
    assert len(grid) == 1
    assert '"lab_id" IN' in grid[0]["sql"]


@pytest.mark.parametrize("boxes", [1, 20])
def test_the_box_list_query_count_is_exact_and_flat(
    *, boxes: int, viewer: User, tree: Tree, make_unit: MakeUnit, query_baseline: QueryBaseline
) -> None:
    for slot in range(2, boxes + 1):
        make_unit(UnitKind.BOX, f"Box {slot}", tree.rack, slot=slot)
    client = logged_in(viewer)
    # Session, user, memberships, the lab, the count and the page.
    with query_baseline("box_list"):
        assert client.get(BOXES_URL).json()["count"] == boxes


# Finding a vial by what the bench scans or types.


@pytest.fixture
def labelled(technician: User, passage0: Passage, make_batch: MakeBatch) -> Vial:
    vial = vials_of(make_batch(passage0, vial_count=3))[1]
    response = logged_in(technician).post(
        f"{VIALS_URL}{vial.public_id}/barcode/",
        {"barcode": "TUBE-0042"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return vial


def found(user: User, code: str) -> list[str]:
    response = logged_in(user).get(VIALS_URL, {"code": code})
    assert response.status_code == 200, response.content
    return [row["public_id"] for row in response.json()["results"]]


def test_a_vial_is_found_by_its_barcode_exactly(viewer: User, labelled: Vial) -> None:
    assert found(viewer, "TUBE-0042") == [str(labelled.public_id)]
    assert found(viewer, "  TUBE-0042 ") == [str(labelled.public_id)]
    assert found(viewer, "tube-0042") == []
    assert found(viewer, "TUBE-004") == []


def test_a_vial_is_found_by_its_label_as_typed(viewer: User, labelled: Vial) -> None:
    accession = str(labelled.batch.strain.accession_number)
    batch = labelled.batch.number
    for typed in (
        f"{accession} / {batch} / 2",
        f"{accession.lower()}/{batch}/2",
        f"  {accession}  /  {batch} /2 ",
    ):
        assert found(viewer, typed) == [str(labelled.public_id)], typed
    assert found(viewer, f"{accession} / {batch} / 9") == []
    assert found(viewer, f"{accession} / {batch}") == []
    assert found(viewer, "/ 1 / 2") == []


def test_a_code_from_another_lab_finds_nothing(
    outsider: User, viewer: User, labelled: Vial, other_lab: Lab
) -> None:
    assert_problem(logged_in(outsider).get(VIALS_URL, {"code": "TUBE-0042"}), 404, "not_found")
    assert found(viewer, "TUBE-0042") == [str(labelled.public_id)]


def test_a_regulated_vial_found_by_its_code_keeps_its_place_masked(
    *, technician: User, viewer: User, mixed: tuple[list[Vial], list[Vial]], tree: Tree
) -> None:
    hidden = mixed[1][0]
    logged_in(technician).post(
        f"{VIALS_URL}{hidden.public_id}/barcode/",
        {"barcode": "REG-1"},
        content_type="application/json",
    )
    response = logged_in(viewer).get(VIALS_URL, {"code": "REG-1"})
    row: dict[str, Any] = response.json()["results"][0]
    assert (row["public_id"], row["location"], row["location_masked"]) == (
        str(hidden.public_id),
        None,
        True,
    )
    assert str(tree.box.public_id) not in json.dumps(response.json())
    assert "Box 1" not in response.content.decode()
