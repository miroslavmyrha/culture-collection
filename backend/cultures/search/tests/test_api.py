"""The contract of the top bar's search (#76): no object in the URL, so no 404 or 403 to give.
Anonymous is 401, every signed-in person gets their own results (none without a lab), nothing
writes, too short a text reads nothing and too long a text is refused."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.core.testing import assert_problem, logged_in
from cultures.labs.tests.conftest import make_user
from cultures.users.models import User

from .fixtures import Stock
from .support import groups, search

pytestmark = pytest.mark.django_db

# Spelled out: the contract coverage test finds it here (core/tests/test_contract_coverage.py).
SEARCH_URL = "/api/v1/me/search/"


def test_anonymous_gets_401_with_the_session_challenge() -> None:
    response = logged_in(None).get(SEARCH_URL, {"q": "MYC 1"})
    assert_problem(response, 401, "not_authenticated")
    assert response["WWW-Authenticate"] == 'Session realm="api"'


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_nothing_writes(method: str, curator: User) -> None:
    assert_problem(getattr(logged_in(None), method)(SEARCH_URL), 401, "not_authenticated")
    assert_problem(getattr(logged_in(curator), method)(SEARCH_URL), 405, "method_not_allowed")


def test_a_person_in_no_lab_finds_nothing(stock: Stock) -> None:
    assert search(make_user("nobody"), "TUBE-1") == {"groups": []}


@pytest.mark.parametrize("text", ["", " ", "T", "  T  "])
def test_too_short_a_text_finds_nothing_and_reads_no_row(
    text: str, stock: Stock, curator: User
) -> None:
    client = logged_in(curator)
    with CaptureQueriesContext(connection) as captured:
        response = client.get(SEARCH_URL, {"q": text})
    assert response.json() == {"groups": []}
    tables = ("strains_strain", "lineage_vial", "deposits_deposit", "distribution_")
    assert not [q for q in captured.captured_queries if any(t in q["sql"] for t in tables)]


def test_without_a_text_it_is_a_field_error(curator: User) -> None:
    assert_problem(logged_in(curator).get(SEARCH_URL), 400, "invalid", attr="q")


@pytest.mark.parametrize(
    ("text", "code"), [("x" * 201, "max_length"), ("TUBE\x00-1", "null_characters_not_allowed")]
)
def test_too_long_a_text_or_a_nul_is_a_field_error(text: str, code: str, curator: User) -> None:
    body = assert_problem(logged_in(curator).get(SEARCH_URL, {"q": text}), 400, "invalid", attr="q")
    assert [error["code"] for error in body["errors"]] == [code]


def test_two_hundred_characters_are_still_searched(curator: User) -> None:
    assert search(curator, "x" * 200) == {"groups": []}


def test_a_hit_has_exactly_the_documented_fields(stock: Stock, curator: User) -> None:
    group = groups(curator, "TUBE-1")["vial"]
    assert set(group) == {"kind", "total", "labs", "hits"}
    assert set(group["labs"][0]) == {"lab", "lab_code", "total"}
    assert set(group["hits"][0]) == {
        "public_id",
        "lab",
        "lab_code",
        "identifier",
        "title",
        "detail",
        "status",
        "exact",
        "strain",
        "location",
        "location_masked",
    }
    # Internal ids never leave the server: every id is the public one.
    hit = group["hits"][0]
    assert hit["public_id"] == str(stock.vials[0].public_id)
    assert hit["lab"] == str(stock.strain.lab.public_id)
    assert hit["strain"] == str(stock.strain.public_id)
