"""Every action of the strain API for every caller: 401 anonymous, 404 outside the lab,
403 for a role without the permission, success for viewer and up reading, for curator and up
writing, and for a manager confirming the end of a restriction (#105). A refused write changes
no row and records no event."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.strains import services
from cultures.strains.models import (
    RestrictionEndProposal,
    Strain,
    StrainIdentification,
    StrainRestriction,
)
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .conftest import GMO, STRAINS_URL, MakeStrain

pytestmark = pytest.mark.django_db


WRITERS = frozenset({Role.CURATOR, Role.MANAGER})


@dataclass(frozen=True)
class Call:
    name: str
    method: str
    path: str  # after the list URL: {strain} and {restriction} are filled in
    write: bool
    allowed: frozenset[Role] = field(default=WRITERS)
    proposed: bool = False  # acts on an open proposal to end the restriction

    def body(self, taxon: Taxon) -> dict[str, Any]:
        proposal = RestrictionEndProposal.objects.filter(confirmed_at=None, withdrawn_at=None)
        named = {"proposal": str(proposal.get().public_id)} if proposal.exists() else {}
        bodies: dict[str, dict[str, Any]] = {
            "reclassify": {
                "taxon": str(taxon.public_id),
                "identified_on": "2026-02-01",
                "method": "m",
                "reason": "r",
            },
            "risk_group": {"risk_group": 2, "reason": "reassessed"},
            "growth": {"temperature_low_c": 30, "atmosphere": "aerobic", "reason": "sheet"},
            "add_restriction": {
                "kind": "cz_rat",
                "reference": "Příloha 2, bod 3",
                "reason": "listed",
            },
            "propose_end": {"reason": "delisted"},
            "confirm_end": named,
            "withdraw_end": {**named, "reason": "still listed"},
        }
        return bodies.get(self.name, {})


CALLS = [
    Call("list", "get", "", write=False),
    Call("retrieve", "get", "{strain}/", write=False),
    Call("history", "get", "{strain}/history/", write=False),
    Call("terms", "get", "{strain}/terms/", write=False),
    Call("reclassify", "post", "{strain}/reclassify/", write=True),
    Call("risk_group", "post", "{strain}/risk-group/", write=True),
    Call("growth", "post", "{strain}/growth/", write=True),
    Call("add_restriction", "post", "{strain}/restrictions/", write=True),
    Call("propose_end", "post", "{strain}/restrictions/{restriction}/end-proposal/", write=True),
    Call(
        "confirm_end",
        "post",
        "{strain}/restrictions/{restriction}/end-proposal/confirm/",
        write=True,
        allowed=frozenset({Role.MANAGER}),
        proposed=True,
    ),
    Call(
        "withdraw_end",
        "post",
        "{strain}/restrictions/{restriction}/end-proposal/withdraw/",
        write=True,
        proposed=True,
    ),
]
ROLES = [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER]


def ready(call: Call) -> None:
    """An open proposal for the calls that act on one, by a curator who is none of the team."""
    if not call.proposed:
        return
    strain = Strain.objects.get()
    proposer = member_of(strain.lab, Role.CURATOR, "proposer")
    with audit_context(channel=Channel.API, actor=proposer, request_id="req-propose"):
        services.strain_restriction_end_propose(
            access=access_for(proposer),
            restriction=StrainRestriction.objects.get(strain=strain),
            reason="delisted",
        )


@pytest.fixture
def strain(make_strain: MakeStrain) -> Strain:
    return make_strain(restrictions=[GMO])


def state() -> tuple[Any, ...]:
    rows = tuple(
        list(m._default_manager.order_by("pk").values())
        for m in (Strain, StrainIdentification, StrainRestriction, RestrictionEndProposal)
    )
    return (*rows, AuditEvent.objects.count())


def url(call: Call) -> str:
    strain = Strain.objects.get()
    restriction = StrainRestriction.objects.get(strain=strain)
    return STRAINS_URL + call.path.format(
        strain=strain.public_id, restriction=restriction.public_id
    )


def send(user: User | None, call: Call, taxon: Taxon) -> Any:
    client = logged_in(user)
    return getattr(client, call.method)(
        url(call), call.body(taxon), content_type="application/json"
    )


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_anonymous_gets_401(call: Call, strain: Strain, mockia: Taxon) -> None:
    ready(call)
    before = state()
    response = send(None, call, mockia)
    assert_problem(response, 401, "not_authenticated")
    assert response.has_header("WWW-Authenticate")
    assert state() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_a_member_of_another_lab_gets_404_for_everything(
    call: Call, strain: Strain, outsider: User, mockia: Taxon
) -> None:
    ready(call)
    before = state()
    assert_problem(send(outsider, call, mockia), 404, "not_found")
    assert state() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
@pytest.mark.parametrize("role", ROLES)
def test_each_role_may_do_what_its_permissions_say(
    call: Call, role: Role, strain: Strain, team: dict[Role, User], mockia: Taxon
) -> None:
    ready(call)
    before = state()
    response = send(team[role], call, mockia)
    if not call.write:
        assert response.status_code == 200, response.content
        return
    if role in call.allowed:
        assert response.status_code == 200, response.content
        assert state() != before
        assert AuditEvent.objects.count() == before[-1] + 1  # one event per write
    else:
        assert_problem(response, 403, "permission_denied")
        assert state() == before


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
def test_a_curator_elsewhere_is_only_what_they_are_here(
    call: Call, strain: Strain, other_lab: Lab, mockia: Taxon
) -> None:
    """Manager in BAC, viewer in MYC: MYC's strains are read-only for them (the role per lab)."""
    ready(call)
    two_labs = member_of(other_lab, Role.MANAGER, "two-labs")
    Membership.objects.create(user=two_labs, lab=strain.lab, role=Role.VIEWER)
    before = state()
    assert_problem(send(two_labs, call, mockia), 403, "permission_denied")
    assert state() == before


def test_an_unknown_strain_and_a_malformed_id_are_404(strain: Strain, curator: User) -> None:
    for tail in ("00000000-0000-4000-8000-000000000999/", "not-a-uuid/"):
        assert_problem(logged_in(curator).get(f"{STRAINS_URL}{tail}"), 404, "not_found")


def test_outside_the_lab_invalid_input_is_still_404(strain: Strain, outsider: User) -> None:
    """The strain is resolved before the body is read: a 400 would confirm it exists."""
    response = logged_in(outsider).post(
        f"{STRAINS_URL}{strain.public_id}/risk-group/",
        {"risk_group": "x"},
        content_type="application/json",
    )
    assert_problem(response, 404, "not_found")


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_strains_are_never_changed_in_place_or_deleted(
    method: str, strain: Strain, manager: User
) -> None:
    response = getattr(logged_in(manager), method)(
        f"{STRAINS_URL}{strain.public_id}/", {}, content_type="application/json"
    )
    assert_problem(response, 405, "method_not_allowed")


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_a_role_without_the_permission_gets_403_before_its_input_is_read(
    call: Call, role: Role, strain: Strain, team: dict[Role, User]
) -> None:
    """The viewset refuses first: invalid input from a viewer is a 403, never a 400 that
    tells them what the form expects. The services refuse too, but only after validation."""
    ready(call)
    response = getattr(logged_in(team[role]), call.method)(
        url(call), {"risk_group": "x", "taxon": "x"}, content_type="application/json"
    )
    assert_problem(response, 403, "permission_denied")


def test_a_member_of_two_labs_sees_only_the_strains_of_the_lab_in_the_url(
    strain: Strain, other_lab: Lab, outsider: User, make_strain: MakeStrain, viewer: User
) -> None:
    """Both labs are in the user's access: only the URL's lab narrows the list and the detail."""
    elsewhere = make_strain(lab=other_lab, actor=outsider, name_as_received="in BAC")
    Membership.objects.create(user=viewer, lab=other_lab, role=Role.VIEWER)
    listed = [row["public_id"] for row in logged_in(viewer).get(STRAINS_URL).json()["results"]]
    assert listed == [str(strain.public_id)]
    assert_problem(logged_in(viewer).get(f"{STRAINS_URL}{elsewhere.public_id}/"), 404, "not_found")
