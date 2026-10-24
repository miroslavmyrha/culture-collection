"""A strain's terms of use on its own page (#19, #78): every version, newest first, with the
MTA each names, for every role that sees the strain. The deposit they belong to only for those
who may open deposits, and never the depositor."""

from typing import Any

import pytest

from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.deposits import services
from cultures.deposits.models import Decision, Deposit, MtaTemplate, Use
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.strains.tests.conftest import MakeStrain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import JANA, LAB_URL, MakeDeposit, as_actor, terms

pytestmark = pytest.mark.django_db

TEACHING_DENIED = tuple(
    (use, Decision.DENY if use == Use.TEACHING else Decision.PERMIT) for use in Use
)


def terms_url(deposit: Deposit) -> str:
    assert deposit.strain is not None
    return f"{LAB_URL}/strains/{deposit.strain.public_id}/terms/"


def read(user: User, deposit: Deposit) -> dict[str, Any]:
    response = logged_in(user).get(terms_url(deposit))
    assert response.status_code == 200, response.content
    data: dict[str, Any] = response.json()
    return data


@pytest.fixture
def accepted(make_deposit: MakeDeposit, exempli: Taxon, mta: MtaTemplate, curator: User) -> Deposit:
    """Accepted under version 1, then version 2 (teaching denied, with the MTA) replaced it."""
    deposit = make_deposit("accepted", taxon=exempli)
    with as_actor(curator):
        services.deposit_terms_replace(
            access=access_for(curator),
            deposit=deposit,
            terms=terms(uses=TEACHING_DENIED, mta=mta),
            reason="The depositor withdrew teaching.",
        )
    return deposit


def test_every_role_reads_every_version_newest_first(
    accepted: Deposit, team: dict[Role, User], mta: MtaTemplate
) -> None:
    for role, user in team.items():
        data = read(user, accepted)
        versions = data["versions"]
        assert [(v["version"], v["is_active"]) for v in versions] == [(2, True), (1, False)], role
        active = versions[0]
        assert {"use": "teaching", "decision": "deny"} in active["uses"], role
        assert active["reason"] == "The depositor withdrew teaching."
        assert active["mta"]["code"] == mta.code
        assert active["mta"]["version"] == mta.version
        assert versions[1]["mta"] is None


def test_the_deposit_only_for_those_who_open_deposits(
    accepted: Deposit, team: dict[Role, User]
) -> None:
    for role, user in team.items():
        deposit = read(user, accepted)["deposit"]
        opens = role in (Role.CURATOR, Role.MANAGER)
        assert deposit == (str(accepted.public_id) if opens else None), role


def test_no_person_in_the_answer(accepted: Deposit, viewer: User, curator: User) -> None:
    """The depositor's contact is personal (deposits.Contact): no reader gets any of it."""
    for user in (viewer, curator):
        body = logged_in(user).get(terms_url(accepted)).content.decode()
        for value in (JANA.name, JANA.email, "Vzorová 1"):
            assert value not in body
        assert '"depositor"' not in body


def test_outside_the_lab_is_not_found(accepted: Deposit, outsider: User) -> None:
    assert_problem(logged_in(outsider).get(terms_url(accepted)), 404, "not_found")
    assert logged_in(None).get(terms_url(accepted)).status_code == 401


def test_a_strain_of_another_lab_is_not_found_here(
    make_strain: MakeStrain, other_lab: Lab, outsider: User, viewer: User
) -> None:
    """Another lab's strain under this lab's URL: not found, for a member of both labs too."""
    foreign = make_strain(lab=other_lab, actor=outsider)
    Membership.objects.create(user=outsider, lab=Lab.objects.get(code="MYC"), role=Role.VIEWER)
    for user in (viewer, outsider):
        response = logged_in(user).get(f"{LAB_URL}/strains/{foreign.public_id}/terms/")
        assert_problem(response, 404, "not_found")


def test_each_strain_reads_its_own_deposits_terms(
    accepted: Deposit, make_deposit: MakeDeposit, exempli: Taxon, viewer: User
) -> None:
    other = make_deposit("accepted", taxon=exempli, name_as_received="Testella exempli D2")
    mine = read(viewer, accepted)["versions"]
    theirs = read(viewer, other)["versions"]
    assert [v["version"] for v in mine] == [2, 1]
    assert [v["version"] for v in theirs] == [1]
    assert not {v["public_id"] for v in mine} & {v["public_id"] for v in theirs}


def test_a_strain_from_no_deposit_has_no_terms(make_strain: MakeStrain, viewer: User) -> None:
    strain = make_strain()
    data = logged_in(viewer).get(f"{LAB_URL}/strains/{strain.public_id}/terms/").json()
    assert data == {"deposit": None, "versions": []}


@pytest.mark.parametrize("replacements", [0, 5])  # one key for both: the count must not grow
def test_the_query_count_is_exact_and_flat(
    *,
    replacements: int,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    curator: User,
    viewer: User,
    query_baseline: QueryBaseline,
) -> None:
    deposit = make_deposit("accepted", taxon=exempli)
    for n in range(replacements):
        with as_actor(curator):
            services.deposit_terms_replace(
                access=access_for(curator), deposit=deposit, terms=terms(), reason=f"Change {n}."
            )
    client, url = logged_in(viewer), terms_url(deposit)
    # Session, user, memberships, the lab, the strain, the versions with their MTA and
    # deposit, their uses.
    with query_baseline("strain_terms"):
        response = client.get(url)
    assert len(response.json()["versions"]) == replacements + 1
