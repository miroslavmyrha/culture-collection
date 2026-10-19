"""The storage API: the tree as one flat list in tree order, a unit with its breadcrumbs and
what it holds, writes that answer with the unit, errors on their fields, exact query counts
that do not grow with the tree, and the global box types."""

from typing import Any

import pytest

from cultures.audit.context import AuditContext
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.labs.access import Access
from cultures.storage import services
from cultures.storage.models import BoxType, StorageUnit, UnitKind, UnitStatus
from cultures.users.models import User

from .conftest import UNITS_URL, MakeUnit, Tree

pytestmark = pytest.mark.django_db
# Global, not under a lab: core/tests/test_contract_coverage.py finds this file by the URL.
BOX_TYPES_URL = "/api/v1/box-types/"


def post(user: User, body: dict[str, Any], tail: str = "") -> Any:
    return logged_in(user).post(f"{UNITS_URL}{tail}", body, content_type="application/json")


def test_the_list_is_the_whole_tree_in_tree_order(
    tree: Tree, make_unit: MakeUnit, viewer: User, box_9x9: BoxType
) -> None:
    make_unit(UnitKind.LN2_TANK, "Tank B", max_risk_group=1, temperature_c=-196)
    second_rack = make_unit(UnitKind.RACK, "Rack 2", tree.freezer, slot=2)
    rows = logged_in(viewer).get(UNITS_URL).json()
    # Each unit right after the one holding it, whatever order they were added in.
    assert [r["name"] for r in rows] == ["Freezer A", "Rack 1", "Box 1", "Rack 2", "Tank B"]
    by_name = {r["name"]: r for r in rows}
    assert by_name["Rack 2"]["parent"] == str(tree.freezer.public_id)
    assert by_name["Freezer A"]["parent"] is None
    assert by_name["Box 1"] == {
        "public_id": str(tree.box.public_id),
        "kind": "box",
        "name": "Box 1",
        "parent": str(tree.rack.public_id),
        "slot": 1,
        "barcode": None,
        "status": "active",
        "box_type": {
            "public_id": str(box_9x9.public_id),
            "name": "Cryobox 9 x 9",
            "rows": 9,
            "cols": 9,
        },
        "rows": 9,
        "cols": 9,
        "temperature_c": None,
        "max_risk_group": None,
        "effective_max_risk_group": 2,
        "path_active": True,
        "created_at": by_name["Box 1"]["created_at"],
        "retired_at": None,
    }
    assert by_name["Tank B"]["effective_max_risk_group"] == 1
    assert str(second_rack.public_id) == by_name["Rack 2"]["public_id"]
    assert "path" not in by_name["Box 1"]  # internal ids never leave the server


def test_retired_units_stay_in_the_tree(
    tree: Tree, viewer: User, as_curator: AuditContext, curator_access: Access
) -> None:
    services.unit_set_status(
        access=curator_access, unit=tree.box, status=UnitStatus.RETIRED, reason="cracked"
    )
    rows = {r["name"]: r for r in logged_in(viewer).get(UNITS_URL).json()}
    assert (rows["Box 1"]["status"], rows["Box 1"]["path_active"]) == ("retired", False)
    assert rows["Box 1"]["retired_at"] is not None


def test_a_unit_shows_its_breadcrumbs_and_what_it_holds(
    tree: Tree, make_unit: MakeUnit, viewer: User
) -> None:
    make_unit(UnitKind.BOX, "Box 0 without a slot", tree.rack)
    make_unit(UnitKind.BOX, "Box 3", tree.rack, slot=3)
    body = logged_in(viewer).get(f"{UNITS_URL}{tree.rack.public_id}/").json()
    assert body["ancestors"] == [
        {"public_id": str(tree.freezer.public_id), "kind": "freezer", "name": "Freezer A"}
    ]
    # By slot, units without one last.
    assert [(c["name"], c["slot"]) for c in body["children"]] == [
        ("Box 1", 1),
        ("Box 3", 3),
        ("Box 0 without a slot", None),
    ]
    box = logged_in(viewer).get(f"{UNITS_URL}{tree.box.public_id}/").json()
    assert [a["name"] for a in box["ancestors"]] == ["Freezer A", "Rack 1"]
    assert box["children"] == []
    freezer = logged_in(viewer).get(f"{UNITS_URL}{tree.freezer.public_id}/").json()
    assert freezer["ancestors"] == []


def test_a_curator_builds_freezer_rack_and_box_through_the_api(
    lab: Any, curator: User, box_9x9: BoxType
) -> None:
    freezer = post(
        curator, {"kind": "freezer", "name": "Freezer C", "temperature_c": -80, "max_risk_group": 2}
    )
    assert freezer.status_code == 201, freezer.content
    rack = post(
        curator,
        {"kind": "rack", "name": "Rack 1", "parent": freezer.json()["public_id"], "slot": 1},
    )
    assert rack.status_code == 201, rack.content
    box = post(
        curator,
        {
            "kind": "box",
            "name": "Box 1",
            "parent": rack.json()["public_id"],
            "slot": 1,
            "box_type": str(box_9x9.public_id),
        },
    )
    assert box.status_code == 201, box.content
    body = box.json()
    assert [a["name"] for a in body["ancestors"]] == ["Freezer C", "Rack 1"]
    assert (body["rows"], body["cols"], body["effective_max_risk_group"]) == (9, 9, 2)


ERRORS = [
    (
        "a box in a box",
        lambda t: {
            "kind": "box",
            "name": "B",
            "parent": str(t.box.public_id),
            "box_type": str(t.box.box_type.public_id),
        },
        "kind_not_allowed",
        "parent",
    ),
    (
        "a freezer in a rack",
        lambda t: {
            "kind": "freezer",
            "name": "F",
            "parent": str(t.rack.public_id),
            "max_risk_group": 1,
        },
        "invalid",
        "parent",
    ),
    (
        "a name taken",
        lambda t: {"kind": "rack", "name": "RACK 1", "parent": str(t.freezer.public_id)},
        "unique",
        "name",
    ),
    (
        "an unknown parent",
        lambda t: {"kind": "rack", "name": "R", "parent": "00000000-0000-4000-8000-000000000999"},
        "invalid",
        "parent",
    ),
    ("an unknown kind", lambda t: {"kind": "shelf", "name": "S"}, "invalid", "kind"),
    (
        "a cap of 5",
        lambda t: {"kind": "freezer", "name": "F", "max_risk_group": 5},
        "invalid",
        "max_risk_group",
    ),
]


@pytest.mark.parametrize(
    ("make_body", "code", "attr"), [e[1:] for e in ERRORS], ids=[e[0] for e in ERRORS]
)
def test_a_refused_unit_is_an_error_on_its_field(
    tree: Tree, curator: User, make_body: Any, code: str, attr: str
) -> None:
    before = StorageUnit.objects.count()
    response = post(curator, make_body(tree))
    body = assert_problem(response, 400, code, attr)
    assert [e["attr"] for e in body["errors"]] == [attr]
    assert StorageUnit.objects.count() == before


def test_a_move_under_itself_is_an_error_on_the_parent(tree: Tree, curator: User) -> None:
    response = post(curator, {"parent": str(tree.box.public_id)}, f"{tree.rack.public_id}/move/")
    assert_problem(response, 400, "cycle", "parent")


def test_a_move_answers_with_the_new_breadcrumbs(
    tree: Tree, curator: User, make_unit: MakeUnit
) -> None:
    tank = make_unit(UnitKind.LN2_TANK, "Tank B")
    response = post(
        curator, {"parent": str(tank.public_id), "slot": 2}, f"{tree.box.public_id}/move/"
    )
    assert response.status_code == 200, response.content
    assert [a["name"] for a in response.json()["ancestors"]] == ["Tank B"]
    assert response.json()["slot"] == 2


def test_retiring_a_unit_that_holds_something_is_refused(tree: Tree, curator: User) -> None:
    response = post(
        curator, {"status": "retired", "reason": "old"}, f"{tree.rack.public_id}/status/"
    )
    assert_problem(response, 422, "unit_not_empty")


def test_a_status_without_a_reason_is_refused_on_the_field(tree: Tree, curator: User) -> None:
    response = post(curator, {"status": "retired", "reason": " "}, f"{tree.box.public_id}/status/")
    assert_problem(response, 400, "invalid", "reason")


def test_a_retired_unit_answers_409(
    tree: Tree, curator: User, as_curator: AuditContext, curator_access: Access
) -> None:
    services.unit_set_status(
        access=curator_access, unit=tree.box, status=UnitStatus.RETIRED, reason="cracked"
    )
    response = post(curator, {"name": "again"}, f"{tree.box.public_id}/edit/")
    assert_problem(response, 409, "unit_retired")


def scoped(queries: list[dict[str, str]]) -> list[str]:
    return [
        q["sql"]
        for q in queries
        if 'FROM "storage_storageunit"' in q["sql"]
        and '"storage_storageunit"."lab_id" IN (' in q["sql"]
    ]


@pytest.mark.parametrize("boxes", [1, 20])
def test_the_tree_query_count_is_exact_and_flat(
    *, boxes: int, tree: Tree, make_unit: MakeUnit, viewer: User, query_baseline: QueryBaseline
) -> None:
    for i in range(boxes - 1):
        make_unit(UnitKind.BOX, f"Box {i + 2}", tree.rack)
    client = logged_in(viewer)
    # Session, user, memberships, the lab, then the whole tree with its box types, parents
    # and the facts of each path in one query.
    with query_baseline("unit_tree") as captured:
        response = client.get(UNITS_URL)
    assert len(response.json()) == boxes + 2
    assert scoped(captured.captured_queries)


@pytest.mark.parametrize("boxes", [1, 20])
def test_the_detail_query_count_is_exact_and_flat(
    *, boxes: int, tree: Tree, make_unit: MakeUnit, viewer: User, query_baseline: QueryBaseline
) -> None:
    for i in range(boxes - 1):
        make_unit(UnitKind.BOX, f"Box {i + 2}", tree.rack)
    client = logged_in(viewer)
    with query_baseline("unit_detail"):
        response = client.get(f"{UNITS_URL}{tree.rack.public_id}/")
    assert len(response.json()["children"]) == boxes


def test_every_signed_in_user_reads_the_box_types(
    box_9x9: BoxType, box_10x10: BoxType, outsider: User
) -> None:
    response = logged_in(outsider).get(BOX_TYPES_URL)
    assert response.status_code == 200
    assert [t["name"] for t in response.json()["results"]] == ["Cryobox 10 x 10", "Cryobox 9 x 9"]
    detail = logged_in(outsider).get(f"{BOX_TYPES_URL}{box_9x9.public_id}/").json()
    assert detail == {
        "public_id": str(box_9x9.public_id),
        "name": "Cryobox 9 x 9",
        "rows": 9,
        "cols": 9,
    }
    assert_problem(logged_in(None).get(BOX_TYPES_URL), 401, "not_authenticated")
    assert_problem(logged_in(outsider).post(BOX_TYPES_URL, {}), 405, "method_not_allowed")
