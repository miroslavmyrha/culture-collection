"""Exact, flat query counts of the search (#76): one match of each kind and many cost the same,
and the lab scope is in the SQL (a count cannot see a lost scope)."""

from collections.abc import Callable

import pytest

from cultures.core.testing import QueryBaseline, logged_in
from cultures.deposits.models import Depositor
from cultures.labs.models import Lab
from cultures.storage.tests.conftest import Tree
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .fixtures import batch_of, intake, label
from .support import SEARCH_URL

pytestmark = pytest.mark.django_db


def scoped(queries: list[dict[str, str]], table: str) -> list[str]:
    return [q["sql"] for q in queries if f'"{table}"."lab_id" IN (' in q["sql"]]


@pytest.fixture
def named(
    *, lab: Lab, curator: User, depositor: Depositor, exempli: Taxon
) -> Callable[[int], None]:
    """`rows` accepted deposits named "Fictivibrio counted <i>", each a strain."""

    def make(rows: int) -> None:
        for i in range(rows):
            intake(lab, curator, depositor, f"Fictivibrio counted {i}", exempli)

    return make


@pytest.mark.parametrize("rows", [1, 7])  # one key for both sizes: the count must not grow
def test_a_search_by_name_costs_the_same_for_one_and_many(
    rows: int, named: Callable[[int], None], manager: User, query_baseline: QueryBaseline
) -> None:
    named(rows)
    client = logged_in(manager)
    # Session, user, memberships; strains, vials and deposits one query each with every lab's
    # total in it. The text is no request number: no request query.
    with query_baseline("search_names") as captured:
        response = client.get(SEARCH_URL, {"q": "Fictivibrio counted"})
    totals = {group["kind"]: group["total"] for group in response.json()["groups"]}
    assert totals == {"strain": rows, "deposit": rows}
    for table in ("strains_strain", "lineage_vial", "deposits_deposit"):
        assert scoped(captured.captured_queries, table), table


@pytest.mark.parametrize("vials", [1, 2])
def test_a_scanned_vial_costs_the_same_for_one_vial_in_the_box_or_two(
    *,
    vials: int,
    lab: Lab,
    curator: User,
    depositor: Depositor,
    exempli: Taxon,
    tree: Tree,
    query_baseline: QueryBaseline,
) -> None:
    strain = intake(lab, curator, depositor, "Fictivibrio scanned", exempli).strain
    assert strain is not None
    for vial in batch_of(curator, strain, vials, tree.box):
        label(f"SCAN-{vial.seq}", vial, curator)
    client = logged_in(curator)
    # Session, user, memberships; the vial, its open placement, the names of its box's path;
    # strains and deposits (a barcode matches neither). The text is no request number.
    with query_baseline("search_vial") as captured:
        response = client.get(SEARCH_URL, {"q": f"SCAN-{vials}"})
    (group,) = response.json()["groups"]
    assert group["hits"][0]["location"]["label"] == f"A{vials}"
    assert scoped(captured.captured_queries, "lineage_vial")


def test_a_request_number_costs_one_query(curator: User, query_baseline: QueryBaseline) -> None:
    client = logged_in(curator)
    # Session, user, memberships; strains, vials, deposits and requests, none found.
    with query_baseline("search_number") as captured:
        response = client.get(SEARCH_URL, {"q": "2026/99"})
    assert response.json() == {"groups": []}
    assert scoped(captured.captured_queries, "distribution_distributionrequest")
