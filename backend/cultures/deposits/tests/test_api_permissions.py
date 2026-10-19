"""Every action of the depositor, MTA template and deposit APIs for every caller: 401
anonymous, 404 outside the lab, success for the roles that have the permission. Curators
and managers read and write deposits; only managers publish an MTA version. Viewers and
technicians see no depositor, template or deposit: a list or a create is 403 for them,
and a single row is 404, as for anything a caller cannot see. A curator publishing an MTA
is 403. A refused write changes no row and records no event."""

from dataclasses import dataclass
from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import assert_problem, logged_in
from cultures.deposits.models import Contact, Deposit, Depositor, DepositTerms, MtaTemplate
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.lineage.models import Passage
from cultures.strains.models import Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import LAB_URL, MakeDeposit, facts_body, terms_body

pytestmark = pytest.mark.django_db

V, T, C, M = Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER


@dataclass(frozen=True)
class Call:
    name: str
    method: str
    path: str  # after the lab URL: {depositor}, {mta} and {deposit} are filled in
    allowed: frozenset[Role]
    status: int = 200

    @property
    def write(self) -> bool:
        return self.method != "get"

    @property
    def detail(self) -> bool:
        return "{" in self.path

    def refusal(self) -> tuple[int, str]:
        """For a role that sees no row of this kind (below curator)."""
        return (404, "not_found") if self.detail else (403, "permission_denied")


READERS = frozenset({C, M})
CALLS = [
    Call("depositor_list", "get", "depositors/", READERS),
    Call("depositor_retrieve", "get", "depositors/{depositor}/", READERS),
    Call("depositor_create", "post", "depositors/", READERS, 201),
    Call("depositor_update", "put", "depositors/{depositor}/", READERS),
    Call("mta_list", "get", "mta-templates/", READERS),
    Call("mta_retrieve", "get", "mta-templates/{mta}/", READERS),
    Call("mta_create", "post", "mta-templates/", frozenset({M}), 201),
    Call("deposit_list", "get", "deposits/", READERS),
    Call("deposit_retrieve", "get", "deposits/{deposit}/", READERS),
    Call("deposit_create", "post", "deposits/", READERS, 201),
    Call("deposit_terms", "post", "deposits/{deposit}/terms/", READERS),
    Call("deposit_start_check", "post", "deposits/{deposit}/start-check/", READERS),
    Call("deposit_accept", "post", "deposits/{deposit}/accept/", READERS),
    Call("deposit_reject", "post", "deposits/{deposit}/reject/", READERS),
]


@dataclass(frozen=True)
class World:
    depositor: Depositor
    mta: MtaTemplate
    received: Deposit
    checking: Deposit
    taxon: Taxon


@pytest.fixture
def world(
    depositor: Depositor, mta: MtaTemplate, make_deposit: MakeDeposit, exempli: Taxon
) -> World:
    return World(depositor, mta, make_deposit(), make_deposit("checking"), exempli)


def url(call: Call, w: World) -> str:
    deposit = w.checking if call.name in ("deposit_accept", "deposit_reject") else w.received
    path = call.path.format(
        depositor=w.depositor.public_id, mta=w.mta.public_id, deposit=deposit.public_id
    )
    return f"{LAB_URL}/{path}"


def body(call: Call, w: World) -> dict[str, Any]:
    bodies: dict[str, dict[str, Any]] = {
        "depositor_create": {"name": "Petr Příklad"},
        "depositor_update": {"name": "Jana Vzorová", "institution": "Changed"},
        "mta_create": {"code": "STD", "title": "Standard MTA", "text": "Version two."},
        "deposit_create": {
            "depositor": str(w.depositor.public_id),
            "received_on": "2026-10-02",
            "condition": "intact",
            "name_as_received": "Testella exempli D2",
            "terms": terms_body(),
        },
        "deposit_terms": {"terms": terms_body(abs_scope="unknown"), "reason": "corrected"},
        "deposit_accept": facts_body(w.taxon),
        "deposit_reject": {"reason": "mixed culture"},
    }
    return bodies.get(call.name, {})


def send(user: User | None, call: Call, w: World) -> Any:
    client = logged_in(user)
    return getattr(client, call.method)(
        url(call, w), body(call, w), content_type="application/json"
    )


def state() -> tuple[Any, ...]:
    tables = (Contact, Depositor, MtaTemplate, Deposit, DepositTerms, Strain, Passage)
    rows = tuple(list(m._default_manager.order_by("pk").values()) for m in tables)
    return (*rows, AuditEvent.objects.count())


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_anonymous_gets_401(call: Call, world: World) -> None:
    before = state()
    response = send(None, call, world)
    assert_problem(response, 401, "not_authenticated")
    assert response.has_header("WWW-Authenticate")
    assert state() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_a_member_of_another_lab_gets_404_for_everything(
    call: Call, world: World, outsider: User
) -> None:
    before = state()
    assert_problem(send(outsider, call, world), 404, "not_found")
    assert state() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
@pytest.mark.parametrize("role", [V, T, C, M])
def test_each_role_may_do_what_its_permissions_say(
    call: Call, role: Role, world: World, team: dict[Role, User]
) -> None:
    before = state()
    response = send(team[role], call, world)
    allowed = role in call.allowed
    refused = call.refusal() if role in (V, T) else (403, "permission_denied")
    expected = call.status if allowed else refused[0]
    assert response.status_code == expected, response.content
    assert (state() != before) == (allowed and call.write)
    assert AuditEvent.objects.count() - before[-1] == (
        {"deposit_accept": 3}.get(call.name, 1) if allowed and call.write else 0
    )


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
def test_a_role_without_the_permission_gets_403_before_its_input_is_read(
    call: Call, world: World, viewer: User
) -> None:
    """Invalid input from a viewer is a 403 or 404, never a 400 that tells them what the form
    wants."""
    response = getattr(logged_in(viewer), call.method)(
        url(call, world), {"name": "", "terms": "x", "reason": ""}, content_type="application/json"
    )
    assert_problem(response, *call.refusal())


def test_a_manager_elsewhere_is_only_what_they_are_here(world: World, other_lab: Lab) -> None:
    """Manager in BAC, technician in MYC: MYC's deposits stay closed to them."""
    two_labs = member_of(other_lab, Role.MANAGER, "two-labs")
    Membership.objects.create(user=two_labs, lab=world.received.lab, role=Role.TECHNICIAN)
    before = state()
    for call in CALLS:
        assert_problem(send(two_labs, call, world), *call.refusal())
    assert state() == before


@pytest.mark.parametrize(
    "path", ["depositors/{depositor}/", "deposits/{deposit}/", "mta-templates/{mta}/"]
)
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_nothing_is_patched_or_deleted(path: str, method: str, world: World, manager: User) -> None:
    target = path.format(
        depositor=world.depositor.public_id,
        deposit=world.received.public_id,
        mta=world.mta.public_id,
    )
    response = getattr(logged_in(manager), method)(
        f"{LAB_URL}/{target}", {}, content_type="application/json"
    )
    assert_problem(response, 405, "method_not_allowed")


def test_unknown_and_malformed_ids_are_404(world: World, curator: User) -> None:
    for tail in ("00000000-0000-4000-8000-000000000999/", "not-a-uuid/"):
        for resource in ("depositors", "deposits", "mta-templates"):
            response = logged_in(curator).get(f"{LAB_URL}/{resource}/{tail}")
            assert_problem(response, 404, "not_found")
