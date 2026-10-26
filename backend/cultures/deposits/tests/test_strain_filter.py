"""The strain list filtered by depositor (#84): the strains accepted from a depositor's
deposits. A depositor is a person's contact, so the filter is for those who may open
deposits and names only this lab's depositors."""

from typing import Any

import pytest

from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.deposits.models import Depositor
from cultures.deposits.services import ContactInput
from cultures.labs.models import Lab
from cultures.strains.tests.conftest import STRAINS_URL, MakeStrain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import MakeDeposit, MakeDepositor

pytestmark = pytest.mark.django_db

PETR = ContactInput("Petr Zkušební", "petr.zkusebni@example.org")


@pytest.fixture
def petr(make_depositor: MakeDepositor) -> Depositor:
    return make_depositor(contact=PETR, institution="Example Institute")


@pytest.fixture
def strains(
    *,
    make_deposit: MakeDeposit,
    make_strain: MakeStrain,
    depositor: Depositor,
    petr: Depositor,
    exempli: Taxon,
) -> None:
    make_deposit("accepted", taxon=exempli, name_as_received="from jana 1")
    make_deposit("accepted", taxon=exempli, name_as_received="from jana 2")
    make_deposit("accepted", taxon=exempli, depositor=petr, name_as_received="from petr")
    make_deposit("received", depositor=petr, name_as_received="not a strain yet")
    make_strain(name_as_received="no deposit")


def listed(user: User, **params: Any) -> list[str]:
    response = logged_in(user).get(STRAINS_URL, params)
    assert response.status_code == 200, response.content
    return [row["name_as_received"] for row in response.json()["results"]]


@pytest.mark.usefixtures("strains")
def test_the_depositor_filter_lists_the_strains_of_that_depositors_deposits(
    curator: User, depositor: Depositor, petr: Depositor
) -> None:
    assert listed(curator) == ["from jana 1", "from jana 2", "from petr", "no deposit"]
    assert listed(curator, depositor=depositor.public_id) == ["from jana 1", "from jana 2"]
    assert listed(curator, depositor=petr.public_id) == ["from petr"]
    assert listed(curator, depositor=petr.public_id, search="jana") == []


@pytest.mark.usefixtures("strains")
def test_another_labs_depositor_is_refused_like_an_unknown_one(
    curator: User, other_lab: Lab, outsider: User, make_depositor: MakeDepositor
) -> None:
    foreign = make_depositor(lab=other_lab, actor=outsider, contact=PETR)
    unknown = "00000000-0000-4000-8000-000000000999"
    for value in (str(foreign.public_id), unknown, "x"):
        response = logged_in(curator).get(STRAINS_URL, {"depositor": value})
        assert_problem(response, 400, "invalid", attr="depositor")
        # The same words for all three: the filter cannot probe for depositors elsewhere.
    foreign_body = logged_in(curator).get(STRAINS_URL, {"depositor": str(foreign.public_id)})
    unknown_body = logged_in(curator).get(STRAINS_URL, {"depositor": unknown})
    assert foreign_body.json()["errors"] == unknown_body.json()["errors"]


@pytest.mark.usefixtures("strains")
def test_a_role_without_deposits_view_cannot_filter_by_depositor(
    viewer: User, technician: User, depositor: Depositor
) -> None:
    for user in (viewer, technician):
        response = logged_in(user).get(STRAINS_URL, {"depositor": str(depositor.public_id)})
        assert_problem(response, 400, "invalid", attr="depositor")
        assert len(listed(user)) == 4  # the list without the filter is theirs as before


@pytest.mark.usefixtures("strains")
def test_the_depositor_filter_adds_one_query(
    curator: User, petr: Depositor, query_baseline: QueryBaseline
) -> None:
    # The list's own queries and the lookup of the depositor, like the taxon filter's.
    client = logged_in(curator)
    with query_baseline("strain_list_by_depositor"):
        response = client.get(STRAINS_URL, {"depositor": str(petr.public_id)})
    assert response.json()["count"] == 1
