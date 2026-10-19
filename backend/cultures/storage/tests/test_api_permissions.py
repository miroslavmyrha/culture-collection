"""Every action of the storage API for every caller: 401 anonymous, 404 outside the lab,
403 for a role without the permission, success for viewer and up reading and for curator
and up writing. A refused write changes no row and records no event."""

from dataclasses import dataclass
from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.storage.models import BoxType, StorageUnit, UnitKind
from cultures.users.models import User

from .conftest import UNITS_URL, MakeUnit, Tree

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Call:
    name: str
    method: str
    path: str  # after the list URL: {unit} is the rack
    write: bool


CALLS = [
    Call("list", "get", "", write=False),
    Call("retrieve", "get", "{unit}/", write=False),
    Call("create", "post", "", write=True),
    Call("edit", "post", "{unit}/edit/", write=True),
    Call("move", "post", "{unit}/move/", write=True),
    Call("set_status", "post", "{unit}/status/", write=True),
]
ALLOWED = {Role.VIEWER: False, Role.TECHNICIAN: False, Role.CURATOR: True, Role.MANAGER: True}


@pytest.fixture
def tank(tree: Tree, make_unit: MakeUnit) -> StorageUnit:
    return make_unit(UnitKind.LN2_TANK, "Tank B")


def body(call: Call, tree: Tree, tank: StorageUnit, box_type: BoxType) -> dict[str, Any]:
    bodies: dict[str, dict[str, Any]] = {
        "create": {
            "kind": "box",
            "name": "Box 2",
            "parent": str(tree.rack.public_id),
            "box_type": str(box_type.public_id),
        },
        "edit": {"name": "Rack 1a"},
        "move": {"parent": str(tank.public_id), "slot": 3},
        "set_status": {"status": "out_of_service", "reason": "alarm"},
    }
    return bodies.get(call.name, {})


def state() -> tuple[Any, ...]:
    return (list(StorageUnit.objects.order_by("pk").values()), AuditEvent.objects.count())


def send(user: User | None, call: Call, tree: Tree, tank: StorageUnit, box_type: BoxType) -> Any:
    url = UNITS_URL + call.path.format(unit=tree.rack.public_id)
    return getattr(logged_in(user), call.method)(
        url, body(call, tree, tank, box_type), content_type="application/json"
    )


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_anonymous_gets_401(call: Call, tree: Tree, tank: StorageUnit, box_9x9: BoxType) -> None:
    before = state()
    response = send(None, call, tree, tank, box_9x9)
    assert_problem(response, 401, "not_authenticated")
    assert response.has_header("WWW-Authenticate")
    assert state() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_a_member_of_another_lab_gets_404_for_everything(
    call: Call, tree: Tree, tank: StorageUnit, box_9x9: BoxType, outsider: User
) -> None:
    before = state()
    assert_problem(send(outsider, call, tree, tank, box_9x9), 404, "not_found")
    assert state() == before


@pytest.mark.parametrize("call", [c for c in CALLS if not c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", list(ALLOWED))
def test_every_role_reads_the_storage(
    *,
    call: Call,
    role: Role,
    tree: Tree,
    tank: StorageUnit,
    box_9x9: BoxType,
    team: dict[Role, User],
) -> None:
    assert send(team[role], call, tree, tank, box_9x9).status_code == 200


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", [r for r, allowed in ALLOWED.items() if allowed])
def test_curators_and_managers_build_the_storage(
    *,
    call: Call,
    role: Role,
    tree: Tree,
    tank: StorageUnit,
    box_9x9: BoxType,
    team: dict[Role, User],
) -> None:
    before = state()
    response = send(team[role], call, tree, tank, box_9x9)
    assert response.status_code == (201 if call.name == "create" else 200), response.content
    assert state() != before
    assert AuditEvent.objects.count() == before[-1] + 1  # one event per write


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", [r for r, allowed in ALLOWED.items() if not allowed])
def test_viewers_and_technicians_get_403_before_their_input_is_read(
    call: Call, role: Role, tree: Tree, team: dict[Role, User]
) -> None:
    """The viewset refuses first: invalid input from a viewer is a 403, never a 400 that
    tells them what the form expects. The services refuse too, but only after validation."""
    before = state()
    url = UNITS_URL + call.path.format(unit=tree.rack.public_id)
    response = getattr(logged_in(team[role]), call.method)(
        url, {"kind": "x", "parent": "x", "status": "x"}, content_type="application/json"
    )
    assert_problem(response, 403, "permission_denied")
    assert state() == before


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
def test_a_curator_elsewhere_is_only_what_they_are_here(
    call: Call, tree: Tree, tank: StorageUnit, box_9x9: BoxType, other_lab: Lab
) -> None:
    """Curator in BAC, viewer in MYC: MYC's storage is read-only for them (the role per lab)."""
    two_labs = member_of(other_lab, Role.CURATOR, "two-labs")
    Membership.objects.create(user=two_labs, lab=tree.rack.lab, role=Role.VIEWER)
    before = state()
    assert_problem(send(two_labs, call, tree, tank, box_9x9), 403, "permission_denied")
    assert state() == before


def test_a_parent_from_a_lab_where_the_user_manages_storage_is_still_refused(
    tree: Tree, other_lab: Lab, curator: User, make_unit: MakeUnit, box_9x9: BoxType
) -> None:
    """The input field resolves units of every lab the user manages; the service holds the
    unit's own lab, with the same message as an unknown unit."""
    Membership.objects.create(user=curator, lab=other_lab, role=Role.CURATOR)
    elsewhere = make_unit(UnitKind.FREEZER, "Freezer B", lab=other_lab)
    before = state()
    response = logged_in(curator).post(
        f"{UNITS_URL}{tree.rack.public_id}/move/",
        {"parent": str(elsewhere.public_id)},
        content_type="application/json",
    )
    body = assert_problem(response, 400, "does_not_exist", "parent")
    assert body["errors"] == [
        {"attr": "parent", "code": "does_not_exist", "detail": "Invalid storage unit."}
    ]
    assert state() == before


def test_an_unknown_unit_and_a_malformed_id_are_404(tree: Tree, curator: User) -> None:
    for tail in ("00000000-0000-4000-8000-000000000999/", "not-a-uuid/"):
        assert_problem(logged_in(curator).get(f"{UNITS_URL}{tail}"), 404, "not_found")


def test_outside_the_lab_invalid_input_is_still_404(tree: Tree, outsider: User) -> None:
    """The lab is resolved before the body is read: a 400 would confirm the lab exists."""
    response = logged_in(outsider).post(UNITS_URL, {"kind": "x"}, content_type="application/json")
    assert_problem(response, 404, "not_found")


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_units_are_never_changed_in_place_or_deleted(
    method: str, tree: Tree, manager: User
) -> None:
    response = getattr(logged_in(manager), method)(
        f"{UNITS_URL}{tree.rack.public_id}/", {}, content_type="application/json"
    )
    assert_problem(response, 405, "method_not_allowed")


def test_a_member_of_two_labs_sees_only_the_units_of_the_lab_in_the_url(
    tree: Tree, other_lab: Lab, outsider: User, make_unit: MakeUnit, viewer: User
) -> None:
    elsewhere = make_unit(UnitKind.FREEZER, "In BAC", lab=other_lab, actor=outsider)
    Membership.objects.create(user=viewer, lab=other_lab, role=Role.VIEWER)
    listed = {row["public_id"] for row in logged_in(viewer).get(UNITS_URL).json()}
    assert listed == {str(u.public_id) for u in (tree.freezer, tree.rack, tree.box)}
    assert_problem(logged_in(viewer).get(f"{UNITS_URL}{elsewhere.public_id}/"), 404, "not_found")
