"""The deposit a strain came from, on the strain's detail (#154): its public id and the name it
goes by, only for those who may open deposits in the strain's lab (deposits.view), in every
answer that carries the detail; null for the other roles and for a strain from no deposit."""

from typing import Any

import pytest

from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.deposits.models import Deposit
from cultures.labs.permissions import Role
from cultures.strains.tests.conftest import MakeStrain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import JANA, LAB_URL, MakeDeposit

pytestmark = pytest.mark.django_db


@pytest.fixture
def accepted(make_deposit: MakeDeposit, exempli: Taxon) -> Deposit:
    return make_deposit("accepted", taxon=exempli)


def detail_url(deposit: Deposit) -> str:
    assert deposit.strain is not None
    return f"{LAB_URL}/strains/{deposit.strain.public_id}/"


def detail(user: User, url: str) -> dict[str, Any]:
    response = logged_in(user).get(url)
    assert response.status_code == 200, response.content
    data: dict[str, Any] = response.json()
    return data


def test_the_deposit_only_for_those_who_open_deposits(
    accepted: Deposit, team: dict[Role, User]
) -> None:
    named = {"public_id": str(accepted.public_id), "name_as_received": "Testella exempli D1"}
    shown = {role: detail(user, detail_url(accepted))["deposit"] for role, user in team.items()}
    assert shown == {
        Role.VIEWER: None,
        Role.TECHNICIAN: None,
        Role.CURATOR: named,
        Role.MANAGER: named,
    }


def test_a_write_answers_with_the_deposit_too(accepted: Deposit, curator: User) -> None:
    """The actions answer with the detail as committed: the same rule holds there."""
    response = logged_in(curator).post(
        f"{detail_url(accepted)}risk-group/",
        {"risk_group": 2, "basis": "NV 361/2007 Sb., Příloha 7", "reason": "Reassessed."},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    assert response.json()["deposit"] == {
        "public_id": str(accepted.public_id),
        "name_as_received": "Testella exempli D1",
    }


def test_a_strain_from_no_deposit_has_none(make_strain: MakeStrain, curator: User) -> None:
    strain = make_strain()
    assert detail(curator, f"{LAB_URL}/strains/{strain.public_id}/")["deposit"] is None


def test_no_person_in_the_deposit(accepted: Deposit, curator: User) -> None:
    """The depositor's contact is personal (deposits.Contact): the detail names none of it."""
    body = logged_in(curator).get(detail_url(accepted)).content.decode()
    for value in (JANA.name, JANA.email, "Vzorová 1"):
        assert value not in body
    assert '"depositor"' not in body


def test_outside_the_lab_is_not_found(accepted: Deposit, outsider: User) -> None:
    """The highest role in another lab: not found, as before, and the deposit is not named."""
    response = logged_in(outsider).get(detail_url(accepted))
    assert_problem(response, 404, "not_found")
    assert str(accepted.public_id) not in response.content.decode()


def test_the_deposit_adds_no_query(
    accepted: Deposit, curator: User, query_baseline: QueryBaseline
) -> None:
    """Joined with the strain (strains.selectors.strain_detail): read without the join, the
    deposit would be one query more."""
    client, url = logged_in(curator), detail_url(accepted)
    with query_baseline("strain_detail_with_deposit"):
        response = client.get(url)
    assert response.json()["deposit"] is not None
