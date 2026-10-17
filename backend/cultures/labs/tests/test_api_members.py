"""Members of a lab through the API: every action for every role, and the grant rules.

Status order: 401 anonymous, 404 not a member of the lab (the same body as a lab
that does not exist), 403 a member whose role may not do it, decided before the
input is validated. A refused write leaves the memberships and the audit table
as they were. No branching inside a test: the expectation is a parameter.
"""

from typing import Any, NamedTuple
from uuid import uuid4

import pytest
from django.test import Client

from cultures.audit.models import AuditEvent
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.users.models import User

from .conftest import LAB_URL, MEMBERS_URL, make_user, member_of, membership, snapshot

pytestmark = pytest.mark.django_db

READ_ROLES = [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER]
NOT_MANAGERS = [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR]


class Action(NamedTuple):
    method: str
    body: dict[str, Any] | None
    allowed: int
    on_list: bool = False  # sent to the list URL (create), otherwise to the member


CREATE = Action("post", {"username": "stranger", "role": "viewer"}, 201, on_list=True)
UPDATE = Action("put", {"role": "curator"}, 200)
PARTIAL_UPDATE = Action("patch", {"role": "curator"}, 200)
DESTROY = Action("delete", None, 204)
DETAIL_WRITES = {"update": UPDATE, "partial_update": PARTIAL_UPDATE, "destroy": DESTROY}
WRITES = {"create": CREATE, **DETAIL_WRITES}


def detail(member: Membership) -> str:
    return f"{MEMBERS_URL}{member.public_id}/"


def send(client: Client, action: Action, member: Membership) -> Any:
    url = MEMBERS_URL if action.on_list else detail(member)
    return getattr(client, action.method)(url, action.body, content_type="application/json")


def events() -> int:
    return AuditEvent.objects.count()


@pytest.fixture
def target(lab: Lab, technician: User) -> Membership:
    """The membership the detail actions act on."""
    return membership(technician, lab)


# Reads


@pytest.mark.parametrize("role", READ_ROLES)
def test_every_member_lists_the_members(role: Role, team: dict[Role, User]) -> None:
    response = logged_in(team[role]).get(MEMBERS_URL)
    assert response.status_code == 200
    assert [row["username"] for row in response.json()["results"]] == [
        "curator",
        "manager",
        "technician",
        "viewer",
    ]


@pytest.mark.parametrize("role", READ_ROLES)
def test_every_member_reads_one_member(
    role: Role, team: dict[Role, User], target: Membership
) -> None:
    response = logged_in(team[role]).get(detail(target))
    assert response.status_code == 200
    assert response.json() == {
        "public_id": str(target.public_id),
        "username": "technician",
        "first_name": target.user.first_name,
        "last_name": target.user.last_name,
        "role": "technician",
        "created_at": target.created_at.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.parametrize("url", [MEMBERS_URL, f"{MEMBERS_URL}{uuid4()}/"])
def test_anonymous_gets_401(url: str, lab: Lab) -> None:
    assert_problem(logged_in(None).get(url), 401, "not_authenticated")


def test_an_outsider_gets_404_for_the_list_and_a_member(outsider: User, target: Membership) -> None:
    client = logged_in(outsider)
    assert_problem(client.get(MEMBERS_URL), 404, "not_found")
    assert_problem(client.get(detail(target)), 404, "not_found")


def test_a_lab_that_does_not_exist_answers_like_a_hidden_one(outsider: User, lab: Lab) -> None:
    hidden = logged_in(outsider).get(MEMBERS_URL)
    missing = logged_in(outsider).get(f"/api/v1/labs/{uuid4()}/members/")
    malformed = logged_in(outsider).get("/api/v1/labs/not-a-uuid/members/")
    bodies = [assert_problem(r, 404, "not_found") for r in (hidden, missing, malformed)]
    assert bodies[0] == bodies[1] == bodies[2]


# Writes: the role matrix


@pytest.mark.parametrize("action", WRITES.values(), ids=WRITES.keys())
@pytest.mark.parametrize("role", NOT_MANAGERS)
def test_only_a_manager_adds_changes_or_removes_a_member(
    action: Action, role: Role, team: dict[Role, User], target: Membership, stranger: User
) -> None:
    before, audit = snapshot(), events()
    assert_problem(send(logged_in(team[role]), action, target), 403, "permission_denied")
    assert (snapshot(), events()) == (before, audit)


@pytest.mark.parametrize("action", WRITES.values(), ids=WRITES.keys())
def test_anonymous_changes_nothing(action: Action, target: Membership, stranger: User) -> None:
    before, audit = snapshot(), events()
    assert_problem(send(logged_in(None), action, target), 401, "not_authenticated")
    assert (snapshot(), events()) == (before, audit)


@pytest.mark.parametrize("action", WRITES.values(), ids=WRITES.keys())
def test_an_outsider_gets_404_and_changes_nothing(
    action: Action, outsider: User, target: Membership, stranger: User
) -> None:
    before, audit = snapshot(), events()
    assert_problem(send(logged_in(outsider), action, target), 404, "not_found")
    assert (snapshot(), events()) == (before, audit)


@pytest.mark.parametrize("action", WRITES.values(), ids=WRITES.keys())
def test_a_manager_runs_every_write(
    action: Action, manager: User, target: Membership, stranger: User
) -> None:
    audit = events()
    assert send(logged_in(manager), action, target).status_code == action.allowed
    assert events() == audit + 1


@pytest.mark.parametrize(
    "action",
    [
        Action("post", {}, 400, on_list=True),
        Action("post", {"username": "stranger", "role": "owner"}, 400, on_list=True),
        Action("patch", {"role": "owner"}, 400),
        Action("put", {}, 400),
    ],
)
def test_a_viewer_gets_403_before_the_input_is_validated(
    action: Action, viewer: User, manager: User, target: Membership, stranger: User
) -> None:
    # A 400 would tell a viewer what the endpoint accepts: the role decides first.
    assert_problem(send(logged_in(viewer), action, target), 403, "permission_denied")
    assert send(logged_in(manager), action, target).status_code == action.allowed  # invalid indeed


# Adding a member


def test_a_manager_adds_an_active_user_with_a_role(lab: Lab, manager: User, stranger: User) -> None:
    body = {"username": "stranger", "role": "curator"}
    response = logged_in(manager).post(MEMBERS_URL, body, content_type="application/json")
    assert response.status_code == 201
    added = Membership.objects.get(public_id=response.json()["public_id"])
    assert (added.user, added.lab, added.role) == (stranger, lab, Role.CURATOR)
    assert response.json()["username"] == "stranger"


def test_smuggled_lab_and_ids_are_ignored(
    lab: Lab, other_lab: Lab, manager: User, stranger: User
) -> None:
    body = {"username": "stranger", "role": "viewer", "lab": str(other_lab.public_id), "id": 1}
    response = logged_in(manager).post(MEMBERS_URL, body, content_type="application/json")
    assert response.status_code == 201
    assert Membership.objects.get(user=stranger).lab == lab


@pytest.mark.parametrize(
    "username",
    ["nobody", "inactive", "x" * 300],
    ids=["unknown", "inactive", "too long"],
)
def test_unknown_and_inactive_users_get_one_generic_error(
    username: str, manager: User, lab: Lab
) -> None:
    make_user("inactive", is_active=False)
    before = snapshot()
    response = logged_in(manager).post(
        MEMBERS_URL, {"username": username, "role": "viewer"}, content_type="application/json"
    )
    body = assert_problem(response, 400, "invalid", attr="username")
    assert body["errors"] == [
        {"attr": "username", "code": "does_not_exist", "detail": "Invalid user."}
    ]
    assert snapshot() == before


def test_an_existing_member_is_refused_on_the_username_field(manager: User, viewer: User) -> None:
    before = snapshot()
    response = logged_in(manager).post(
        MEMBERS_URL, {"username": "viewer", "role": "curator"}, content_type="application/json"
    )
    body = assert_problem(response, 400, "already_member", attr="username")
    assert body["errors"][0]["code"] == "already_member"
    assert snapshot() == before


def test_an_unknown_role_is_refused_on_the_role_field(manager: User, stranger: User) -> None:
    response = logged_in(manager).post(
        MEMBERS_URL, {"username": "stranger", "role": "owner"}, content_type="application/json"
    )
    assert_problem(response, 400, "invalid", attr="role")
    assert not Membership.objects.filter(user=stranger).exists()


# Changing and removing


def test_a_manager_changes_a_role(manager: User, target: Membership) -> None:
    response = logged_in(manager).patch(
        detail(target), {"role": "curator"}, content_type="application/json"
    )
    target.refresh_from_db()
    assert (response.json()["role"], target.role) == ("curator", Role.CURATOR)


def test_an_empty_patch_changes_nothing_and_records_nothing(
    manager: User, target: Membership
) -> None:
    before, audit = snapshot(), events()
    response = logged_in(manager).patch(detail(target), {}, content_type="application/json")
    assert (response.status_code, response.json()["role"]) == (200, "technician")
    assert (snapshot(), events()) == (before, audit)


def test_put_needs_the_role(manager: User, target: Membership) -> None:
    response = logged_in(manager).put(detail(target), {}, content_type="application/json")
    assert_problem(response, 400, "invalid", attr="role")


def test_a_removed_member_loses_access_at_once(lab: Lab, manager: User, viewer: User) -> None:
    client = logged_in(viewer)  # signed in before, the session stays valid
    assert client.get(LAB_URL).status_code == 200
    assert logged_in(manager).delete(detail(membership(viewer, lab))).status_code == 204
    assert_problem(client.get(LAB_URL), 404, "not_found")
    assert_problem(client.get(MEMBERS_URL), 404, "not_found")
    assert client.get("/api/v1/labs/").json()["results"] == []


def test_the_last_manager_can_neither_be_demoted_nor_removed(lab: Lab, manager: User) -> None:
    own = detail(membership(manager, lab))
    client = logged_in(manager)
    before, audit = snapshot(), events()
    demoted = client.patch(own, {"role": "curator"}, content_type="application/json")
    assert_problem(demoted, 422, "last_manager")
    assert_problem(client.delete(own), 422, "last_manager")
    assert (snapshot(), events()) == (before, audit)


def test_a_manager_steps_down_when_another_manager_remains(lab: Lab, manager: User) -> None:
    member_of(lab, Role.MANAGER, "second-manager")
    response = logged_in(manager).patch(
        detail(membership(manager, lab)), {"role": "viewer"}, content_type="application/json"
    )
    assert response.status_code == 200
    assert membership(manager, lab).role == Role.VIEWER


@pytest.mark.parametrize(
    ("method", "body"), [("get", None), ("patch", {"role": "viewer"}), ("delete", None)]
)
def test_a_member_of_another_lab_is_not_found_through_this_lab(
    method: str, body: dict[str, str] | None, lab: Lab, other_lab: Lab, manager: User
) -> None:
    # The manager manages both labs: only the lab in the URL keeps them apart.
    Membership.objects.create(user=manager, lab=other_lab, role=Role.MANAGER)
    elsewhere = member_of(other_lab, Role.TECHNICIAN, "elsewhere")
    url = detail(membership(elsewhere, other_lab))
    before, audit = snapshot(), events()
    response = getattr(logged_in(manager), method)(url, body, content_type="application/json")
    assert_problem(response, 404, "not_found")
    assert (snapshot(), events()) == (before, audit)


def test_an_inactive_user_is_signed_out(viewer: User) -> None:
    client = logged_in(viewer)
    viewer.is_active = False
    viewer.save()
    # Django's backend drops the session of an inactive user (ModelBackend.get_user).
    assert_problem(client.get(MEMBERS_URL), 401, "not_authenticated")
