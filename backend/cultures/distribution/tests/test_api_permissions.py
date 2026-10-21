"""Every action of the requester, permit, document and request APIs for every caller: 401
anonymous, 404 outside the lab, success for the roles that have the permission. Viewers and
technicians read requests (no person, no place), but see no requester, permit or document:
a list or a create is 403 for them, a single row 404, as for anything a caller cannot see.
Writes are the curators' and managers'. A refused write changes no row and records no event,
and a role without the permission is refused before its input is read."""

from dataclasses import dataclass
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent
from cultures.core.testing import assert_problem, logged_in
from cultures.distribution.models import (
    DistributionRequest,
    PermitKind,
    RecipientPermit,
    Requester,
)
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.users.models import User

from .support import LAB_URL, PDF, Supply, accept_mtas, add_permit, snapshot, submit

pytestmark = pytest.mark.django_db

V, T, C, M = Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER
EVERYONE = frozenset({V, T, C, M})
CURATORS = frozenset({C, M})


@dataclass(frozen=True)
class Call:
    name: str
    method: str
    path: str  # after the lab URL: {requester}, {permit}, {document}, {request} filled in
    allowed: frozenset[Role]
    status: int = 200
    events: int = 1  # what a permitted write records
    multipart: bool = False
    # Rows of a kind viewers and technicians cannot see: 404 for one, 403 for a list.
    hidden: bool = False

    @property
    def write(self) -> bool:
        return self.method != "get"

    def refusal(self) -> tuple[int, str]:
        if self.hidden and "{" in self.path:
            return 404, "not_found"
        return 403, "permission_denied"


CALLS = [
    Call("requester_list", "get", "requesters/", CURATORS, hidden=True),
    Call("requester_retrieve", "get", "requesters/{requester}/", CURATORS, hidden=True),
    Call("requester_create", "post", "requesters/", CURATORS, 201, hidden=True),
    Call("requester_update", "put", "requesters/{requester}/", CURATORS, hidden=True),
    Call("permit_list", "get", "recipient-permits/", CURATORS, hidden=True),
    Call("permit_retrieve", "get", "recipient-permits/{permit}/", CURATORS, hidden=True),
    Call("permit_create", "post", "recipient-permits/", CURATORS, 201, multipart=True, hidden=True),
    Call("permit_end", "post", "recipient-permits/{permit}/end/", CURATORS, hidden=True),
    Call("document_retrieve", "get", "documents/{document}/", CURATORS, hidden=True),
    Call("request_list", "get", "requests/", EVERYONE),
    Call("request_retrieve", "get", "requests/{request}/", EVERYONE),
    Call("request_create", "post", "requests/", CURATORS, 201, events=2),
    Call("request_approve", "post", "requests/{accepted}/approve/", CURATORS, events=3),
    Call("request_reject", "post", "requests/{request}/reject/", CURATORS),
    Call("request_cancel", "post", "requests/{request}/cancel/", CURATORS),
    Call(
        "request_acceptances",
        "post",
        "requests/{request}/acceptances/",
        CURATORS,
        201,
        multipart=True,
    ),
]


@dataclass(frozen=True)
class World:
    requester: Requester
    permit: RecipientPermit
    request: DistributionRequest
    accepted: DistributionRequest
    strain_id: str
    mta_id: str


@pytest.fixture
def world(
    as_curator: AuditContext, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> World:
    strain = supply()
    permit = add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    request = submit(curator, lab, requester, [(strain, 1)])
    accepted = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, accepted)
    mta = request.lines.get().mta
    assert mta is not None
    return World(requester, permit, request, accepted, str(strain.public_id), str(mta.public_id))


def url(call: Call, w: World) -> str:
    path = call.path.format(
        requester=w.requester.public_id,
        permit=w.permit.public_id,
        document=w.permit.document.public_id,
        request=w.request.public_id,
        accepted=w.accepted.public_id,
    )
    return f"{LAB_URL}/{path}"


def body(call: Call, w: World) -> dict[str, Any]:
    requester = {
        "institution": "Example Institute of Microbiology",
        "legal_form": "legal_person",
        "country": "CZ",
        "lab_evidence": "The department page lists a microbiology laboratory.",
        "lab_confirmed_on": "2026-10-01",
        "name": "Petra Ukázková",
        "postal_address": "Testovací 5, Brno",
    }
    bodies: dict[str, dict[str, Any]] = {
        "requester_create": requester,
        "requester_update": {**requester, "country": "SK"},
        "permit_create": {
            "requester": str(w.requester.public_id),
            "kind": "sujb_rat_notice",
            "issuer": "SÚJB",
            "issuer_country": "CZ",
            "reference": "DEV/2 (invented example)",
            "valid_from": "2026-01-01",
            "file": SimpleUploadedFile("notice.pdf", PDF, "application/pdf"),
        },
        "permit_end": {"ended_on": "2026-06-01", "reason": "revoked"},
        "request_create": {
            "requester": str(w.requester.public_id),
            "use": "research_noncommercial",
            "end_use": "Teaching.",
            "containment_level": 2,
            "lines": [{"strain": w.strain_id, "quantity": 1}],
        },
        "request_approve": {"reason": ""},
        "request_reject": {"reason": "no laboratory"},
        "request_cancel": {"reason": "withdrawn"},
        "request_acceptances": {
            "mta": w.mta_id,
            "signer_name": "Karel Podpisový",
            "signer_role": "head_of_institution",
            "authorised_signatory": "true",
            "accepted_on": "2026-10-02",
            "file": SimpleUploadedFile("signed.pdf", PDF, "application/pdf"),
        },
    }
    return bodies.get(call.name, {})


def send(user: User | None, call: Call, w: World, payload: dict[str, Any] | None = None) -> Any:
    client = logged_in(user)
    data = body(call, w) if payload is None else payload
    if call.multipart:
        return getattr(client, call.method)(url(call, w), data)
    return getattr(client, call.method)(url(call, w), data, content_type="application/json")


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_anonymous_gets_401(call: Call, world: World) -> None:
    before = snapshot()
    response = send(None, call, world)
    assert_problem(response, 401, "not_authenticated")
    assert response.has_header("WWW-Authenticate")
    assert snapshot() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_a_member_of_another_lab_gets_404_for_everything(
    call: Call, world: World, outsider: User
) -> None:
    before = snapshot()
    assert_problem(send(outsider, call, world), 404, "not_found")
    assert snapshot() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
@pytest.mark.parametrize("role", [V, T, C, M])
def test_each_role_may_do_what_its_permissions_say(
    call: Call, role: Role, world: World, team: dict[Role, User]
) -> None:
    before = snapshot()
    response = send(team[role], call, world)
    allowed = role in call.allowed
    expected = call.status if allowed else call.refusal()[0]
    assert response.status_code == expected, response.content
    assert (snapshot() != before) == (allowed and call.write)
    assert AuditEvent.objects.count() - before[-2] == (call.events if allowed and call.write else 0)


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", [V, T])
def test_a_role_without_the_permission_is_refused_before_its_input_is_read(
    call: Call, role: Role, world: World, team: dict[Role, User]
) -> None:
    """Invalid input from a viewer is a 403 or 404, never a 400 that tells them what the form
    wants."""
    # Each body is invalid for its action (an approval's reason is optional, but not this long):
    # a check of the input before the role would answer 400.
    payload = {"reason": "x" * 2001, "requester": "x", "lines": "x", "kind": "x", "ended_on": "x"}
    assert_problem(send(team[role], call, world, payload), *call.refusal())


def test_a_manager_elsewhere_is_only_what_they_are_here(world: World, other_lab: Lab) -> None:
    """Manager in BAC, viewer in MYC: MYC's requests are read, nothing else."""
    two_labs = member_of(other_lab, Role.MANAGER, "two-labs")
    Membership.objects.create(user=two_labs, lab=world.request.lab, role=Role.VIEWER)
    before = snapshot()
    for call in CALLS:
        response = send(two_labs, call, world)
        if V in call.allowed:
            assert response.status_code == call.status, call.name
        else:
            assert_problem(response, *call.refusal())
    assert snapshot() == before


UNROUTED = [
    (path, method)
    for path in ("requesters/{requester}/", "recipient-permits/{permit}/", "requests/{request}/")
    for method in ("patch", "delete", "put")
    if (path, method) != ("requesters/{requester}/", "put")  # a requester changes with put
] + [("documents/{document}/", method) for method in ("patch", "delete", "put", "post")]


@pytest.mark.parametrize(("path", "method"), UNROUTED)
def test_nothing_is_patched_or_deleted(path: str, method: str, world: World, manager: User) -> None:
    target = Call("x", method, path, CURATORS)
    response = getattr(logged_in(manager), method)(
        url(target, world), {}, content_type="application/json"
    )
    assert_problem(response, 405, "method_not_allowed")


def test_unknown_and_malformed_ids_are_404(world: World, curator: User) -> None:
    for tail in ("00000000-0000-4000-8000-000000000999/", "not-a-uuid/"):
        for resource in ("requesters", "recipient-permits", "documents", "requests"):
            response = logged_in(curator).get(f"{LAB_URL}/{resource}/{tail}")
            assert_problem(response, 404, "not_found")
