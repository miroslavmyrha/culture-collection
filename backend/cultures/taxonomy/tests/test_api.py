"""The taxonomy API: every signed-in user reads it, nobody writes it, and it finds names.

Taxa have no lab, so the contract's outsider does not exist here: a user in no lab reads
the same taxa as a member (core/tests/test_contract_coverage.py, EXEMPT).
"""

import pytest
from model_bakery import baker

from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.taxonomy.models import IdentifierSystem, Rank, Taxon, TaxonIdentifier
from cultures.users.models import User

from .conftest import make_taxon

pytestmark = pytest.mark.django_db
TAXA_URL = "/api/v1/taxa/"


@pytest.fixture
def anyone() -> User:
    """Signed in, in no lab."""
    user: User = baker.make(User, username="anyone")
    return user


def test_anonymous_gets_401(exempli: Taxon) -> None:
    for url in (TAXA_URL, f"{TAXA_URL}{exempli.public_id}/"):
        response = logged_in(None).get(url)
        assert_problem(response, 401, "not_authenticated")
        assert response.has_header("WWW-Authenticate")


def test_any_signed_in_user_reads_a_taxon_with_its_synonymy_and_ids(
    anyone: User, exempli: Taxon, fictivibrio: Taxon, testella: Taxon
) -> None:
    TaxonIdentifier.objects.create(taxon=exempli, system=IdentifierSystem.NCBI, value="900003")
    body = logged_in(anyone).get(f"{TAXA_URL}{fictivibrio.public_id}/").json()
    assert body == {
        "public_id": str(fictivibrio.public_id),
        "name": "Fictivibrio exempli",
        "authority": fictivibrio.authority,
        "rank": "species",
        "status": "synonym",
        "parent": None,
        "accepted": {
            "public_id": str(exempli.public_id),
            "name": "Testella exempli",
            "authority": "Doe 2001",
            "rank": "species",
            "status": "accepted",
        },
        "identifiers": [],
    }
    accepted = logged_in(anyone).get(f"{TAXA_URL}{exempli.public_id}/").json()
    assert accepted["parent"]["public_id"] == str(testella.public_id)
    assert accepted["identifiers"] == [{"system": "ncbi", "value": "900003"}]
    assert "id" not in accepted


def test_an_unknown_or_malformed_id_is_404(anyone: User) -> None:
    for tail in ("00000000-0000-4000-8000-000000000999/", "not-a-uuid/"):
        assert_problem(logged_in(anyone).get(f"{TAXA_URL}{tail}"), 404, "not_found")


def test_search_finds_names_by_part(
    anyone: User, testella: Taxon, exempli: Taxon, mockia: Taxon
) -> None:
    rows = logged_in(anyone).get(TAXA_URL, {"search": "exem"}).json()["results"]
    assert [row["name"] for row in rows] == ["Testella exempli"]
    rows = logged_in(anyone).get(TAXA_URL, {"search": "testella"}).json()["results"]
    assert [row["name"] for row in rows] == ["Testella", "Testella exempli"]


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_nobody_writes_taxa_through_the_api(method: str, anyone: User, exempli: Taxon) -> None:
    url = TAXA_URL if method == "post" else f"{TAXA_URL}{exempli.public_id}/"
    response = getattr(logged_in(anyone), method)(url, {}, content_type="application/json")
    assert_problem(response, 405, "method_not_allowed")
    assert Taxon.objects.get(pk=exempli.pk).name == "Testella exempli"


@pytest.mark.parametrize("rows", [1, 20])
def test_the_list_query_count_is_exact_and_flat(
    rows: int, anyone: User, query_baseline: QueryBaseline
) -> None:
    genus = make_taxon("Genus", Rank.GENUS)
    for i in range(rows - 1):
        taxon = make_taxon(f"Genus species{i:02}", Rank.SPECIES, genus)
        TaxonIdentifier.objects.create(taxon=taxon, system=IdentifierSystem.LPSN, value=f"x{i}")
    client = logged_in(anyone)
    # Session, user, count, page with parent and accepted joined, the ids prefetched.
    with query_baseline("taxon_list"):
        response = client.get(TAXA_URL, {"search": "genus"})
    assert response.json()["count"] == rows
