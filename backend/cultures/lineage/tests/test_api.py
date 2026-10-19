"""The passage, batch and vial API end to end: what preserving, placing and a state change
send and answer, the problem bodies of the refusals, the strain filter, and exact query
counts at 1 and 20 rows."""

from typing import Any

import pytest

from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.lineage.models import Batch, Passage, Vial, VialPlacement
from cultures.storage.tests.conftest import Tree
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import BATCHES_URL, PASSAGES_URL, VIALS_URL, MakeBatch, snapshot, vials_of

pytestmark = pytest.mark.django_db


def preserve_body(passage: Passage, **changes: Any) -> dict[str, Any]:
    return {
        "passage": str(passage.public_id),
        "method": "lyophilised",
        "purpose": "seed",
        "cryoprotectant": "skim milk",
        "preserved_on": "2026-10-02",
        "vial_count": 2,
        **changes,
    }


def test_a_technician_preserves_into_a_box_and_reads_the_vials_back(
    technician: User, passage0: Passage, strain: Strain, tree: Tree
) -> None:
    client = logged_in(technician)
    response = client.post(
        BATCHES_URL,
        preserve_body(passage0, box=str(tree.box.public_id)),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    batch = Batch.objects.get()
    assert response.json() == {
        "public_id": str(batch.public_id),
        "strain": str(strain.public_id),
        "number": 1,
        "passage": str(passage0.public_id),
        "passage_number": 0,
        "method": "lyophilised",
        "cryoprotectant": "skim milk",
        "preserved_on": "2026-10-02",
        "purpose": "seed",
        "status": "pending_check",
        "vial_count_created": 2,
        "vials_available": 2,
        "created_at": response.json()["created_at"],
    }
    vials = client.get(VIALS_URL, {"strain": str(strain.public_id)}).json()["results"]
    assert [(v["label"], v["seq"], v["status"], v["location"]["label"]) for v in vials] == [
        (f"{strain.accession_number} / 1 / 1", 1, "available", "A1"),
        (f"{strain.accession_number} / 1 / 2", 2, "available", "A2"),
    ]


@pytest.mark.parametrize(
    ("changes", "attr", "code"),
    [
        ({"vial_count": 0}, "vial_count", "min_value"),
        ({"vial_count": 201}, "vial_count", "max_value"),
        ({"method": "dried"}, "method", "invalid_choice"),
        ({"passage": "00000000-0000-4000-8000-000000000999"}, "passage", "does_not_exist"),
        ({"preserved_on": "2999-01-01"}, "preserved_on", "invalid"),
        ({"box": "00000000-0000-4000-8000-000000000999"}, "box", "does_not_exist"),
    ],
)
def test_preserving_refuses_bad_input_on_its_field(
    technician: User, passage0: Passage, changes: dict[str, Any], attr: str, code: str
) -> None:
    before = snapshot()
    body = {**preserve_body(passage0), **changes}
    response = logged_in(technician).post(BATCHES_URL, body, content_type="application/json")
    problem = assert_problem(response, 400, "invalid", attr)
    assert [e["code"] for e in problem["errors"] if e["attr"] == attr] == [code]
    assert snapshot() == before


def test_a_full_box_is_a_field_error_on_the_box(
    technician: User, passage0: Passage, make_batch: MakeBatch, tree: Tree
) -> None:
    make_batch(passage0, vial_count=80, box=tree.box)
    response = logged_in(technician).post(
        BATCHES_URL,
        preserve_body(passage0, box=str(tree.box.public_id)),
        content_type="application/json",
    )
    body = assert_problem(response, 400, "box_full", "box")
    assert body["errors"][0]["detail"] == "This box has 1 free positions, the batch 2 vials."


def test_a_subculture_through_the_api(technician: User, passage0: Passage, strain: Strain) -> None:
    response = logged_in(technician).post(
        PASSAGES_URL, {"source_passage": str(passage0.public_id)}, content_type="application/json"
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["number"], body["source_kind"], body["source_passage"], body["strain"]) == (
        1,
        "passage",
        str(passage0.public_id),
        str(strain.public_id),
    )


def test_placing_and_the_conflicts_it_answers(
    technician: User, passage0: Passage, make_batch: MakeBatch, tree: Tree
) -> None:
    first, second = vials_of(make_batch(passage0, vial_count=2))
    client = logged_in(technician)

    def place(vial: Vial, row: int, col: int) -> Any:
        return client.post(
            f"{VIALS_URL}{vial.public_id}/place/",
            {"box": str(tree.box.public_id), "row": row, "col": col},
            content_type="application/json",
        )

    assert place(first, 2, 5).json()["location"]["label"] == "B5"
    assert_problem(place(second, 2, 5), 409, "position_taken")
    assert_problem(place(second, 10, 1), 400, "outside_box", "row")
    assert_problem(place(second, 27, 1), 400, "invalid", "row")
    moved = place(first, 9, 9).json()["location"]
    assert (moved["label"], moved["path"]) == ("I9", ["Freezer A", "Rack 1", "Box 1"])
    assert VialPlacement.objects.filter(vial=first).count() == 2


def test_a_state_change_through_the_api(
    technician: User, passage0: Passage, make_batch: MakeBatch
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    url = f"{VIALS_URL}{vial.public_id}/status/"
    client = logged_in(technician)
    assert_problem(
        client.post(url, {"status": "reserved", "reason": "r"}, content_type="application/json"),
        400,
        "invalid",
        "status",
    )
    assert_problem(
        client.post(url, {"status": "destroyed", "reason": "r"}, content_type="application/json"),
        400,
        "transition_not_allowed",
        "status",
    )
    assert_problem(
        client.post(url, {"status": "lost", "reason": " "}, content_type="application/json"),
        400,
        "invalid",
        "reason",
    )
    done = client.post(
        url, {"status": "lost", "reason": "not in its place"}, content_type="application/json"
    )
    assert (done.status_code, done.json()["status"]) == (200, "lost")


def test_a_revival_through_the_api(
    technician: User, passage0: Passage, make_batch: MakeBatch
) -> None:
    vial = vials_of(make_batch(passage0, vial_count=1))[0]
    response = logged_in(technician).post(f"{VIALS_URL}{vial.public_id}/revive/")
    assert response.status_code == 201
    assert (response.json()["number"], response.json()["source_kind"]) == (1, "vial")
    assert_problem(
        logged_in(technician).post(f"{VIALS_URL}{vial.public_id}/revive/"),
        400,
        "transition_not_allowed",
        "status",
    )


def test_the_strain_filter_narrows_every_list(
    viewer: User, passage0: Passage, regulated: Strain, make_batch: MakeBatch, strain: Strain
) -> None:
    make_batch(passage0, vial_count=1)
    make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=2)
    client = logged_in(viewer)
    for url, count in ((PASSAGES_URL, 1), (BATCHES_URL, 1), (VIALS_URL, 1)):
        assert client.get(url, {"strain": str(strain.public_id)}).json()["count"] == count, url
    assert client.get(VIALS_URL, {"strain": str(regulated.public_id)}).json()["count"] == 2
    assert_problem(client.get(VIALS_URL, {"strain": "nope"}), 400, "invalid", "strain")


def scoped(queries: list[dict[str, Any]], table: str) -> bool:
    return any(f'FROM "{table}"' in q["sql"] and '"lab_id" IN' in q["sql"] for q in queries)


@pytest.mark.parametrize("vials", [1, 20])
def test_the_vial_list_query_count_is_exact_and_flat(
    *,
    vials: int,
    viewer: User,
    passage0: Passage,
    make_batch: MakeBatch,
    tree: Tree,
    query_baseline: QueryBaseline,
) -> None:
    make_batch(passage0, vial_count=vials, box=tree.box)
    client = logged_in(viewer)
    # Session, user, memberships, the lab, the count, the page, the open placements with
    # their boxes, the box paths, and whether the reader holds the location grant.
    with query_baseline("vial_list") as captured:
        response = client.get(VIALS_URL)
    assert response.json()["count"] == vials
    assert scoped(captured.captured_queries, "lineage_vial")


@pytest.mark.parametrize("batches", [1, 20])
def test_the_batch_and_passage_lists_are_flat(
    *,
    batches: int,
    viewer: User,
    passage0: Passage,
    make_batch: MakeBatch,
    query_baseline: QueryBaseline,
) -> None:
    for _ in range(batches):
        make_batch(passage0, vial_count=1)
    client = logged_in(viewer)
    with query_baseline("batch_list") as captured:
        assert client.get(BATCHES_URL).json()["count"] == batches
    assert scoped(captured.captured_queries, "lineage_batch")
    with query_baseline("passage_list"):
        assert client.get(PASSAGES_URL).json()["count"] == 1
