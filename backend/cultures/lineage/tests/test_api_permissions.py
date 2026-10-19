"""Every action of the passage, batch and vial API for every caller: 401 anonymous, 404
outside the lab, 403 for a role without the permission (before the input is read), success
for viewer and up reading and for technician and up handling vials. A refused write changes
no row and records no event."""

from dataclasses import dataclass
from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.core.testing import assert_problem, logged_in
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.lineage.models import Passage, Vial
from cultures.storage import services as storage
from cultures.storage.models import UnitKind
from cultures.storage.tests.conftest import Tree, make_box_type
from cultures.users.models import User

from .support import BATCHES_URL, PASSAGES_URL, VIALS_URL, MakeBatch, snapshot, vials_of

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Call:
    name: str
    method: str
    url: str  # {vial} and {passage} are filled in
    write: bool
    status: int = 200


CALLS = [
    Call("passage_list", "get", PASSAGES_URL, write=False),
    Call("passage_retrieve", "get", PASSAGES_URL + "{passage}/", write=False),
    Call("subculture", "post", PASSAGES_URL, write=True, status=201),
    Call("batch_list", "get", BATCHES_URL, write=False),
    Call("preserve", "post", BATCHES_URL, write=True, status=201),
    Call("vial_list", "get", VIALS_URL, write=False),
    Call("vial_retrieve", "get", VIALS_URL + "{vial}/", write=False),
    Call("place", "post", VIALS_URL + "{vial}/place/", write=True),
    Call("set_status", "post", VIALS_URL + "{vial}/status/", write=True),
    Call("barcode", "post", VIALS_URL + "{vial}/barcode/", write=True),
    Call("revive", "post", VIALS_URL + "{vial}/revive/", write=True, status=201),
]
HANDLERS = {Role.VIEWER: False, Role.TECHNICIAN: True, Role.CURATOR: True, Role.MANAGER: True}


@pytest.fixture
def vial(make_batch: MakeBatch, passage0: Passage) -> Vial:
    return vials_of(make_batch(passage0, vial_count=1))[0]


def body(call: Call, passage: Passage, tree: Tree) -> dict[str, Any]:
    bodies: dict[str, dict[str, Any]] = {
        "subculture": {"source_passage": str(passage.public_id)},
        "preserve": {
            "passage": str(passage.public_id),
            "method": "cryo_ln2",
            "purpose": "seed",
            "preserved_on": "2026-10-01",
            "vial_count": 2,
            "box": str(tree.box.public_id),
        },
        "place": {"box": str(tree.box.public_id), "row": 2, "col": 2},
        "set_status": {"status": "quarantined", "reason": "contamination suspected"},
        "barcode": {"barcode": "TUBE-7"},
    }
    return bodies.get(call.name, {})


def send(user: User | None, call: Call, vial: Vial, passage: Passage, tree: Tree) -> Any:
    url = call.url.format(vial=vial.public_id, passage=passage.public_id)
    return getattr(logged_in(user), call.method)(
        url, body(call, passage, tree), content_type="application/json"
    )


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_anonymous_gets_401(call: Call, vial: Vial, passage0: Passage, tree: Tree) -> None:
    before = snapshot()
    response = send(None, call, vial, passage0, tree)
    assert_problem(response, 401, "not_authenticated")
    assert snapshot() == before


@pytest.mark.parametrize("call", CALLS, ids=lambda c: c.name)
def test_a_member_of_another_lab_gets_404_for_everything(
    call: Call, vial: Vial, passage0: Passage, tree: Tree, outsider: User
) -> None:
    before = snapshot()
    assert_problem(send(outsider, call, vial, passage0, tree), 404, "not_found")
    assert snapshot() == before


@pytest.mark.parametrize("call", [c for c in CALLS if not c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", list(HANDLERS))
def test_every_role_reads(
    *, call: Call, role: Role, vial: Vial, passage0: Passage, tree: Tree, team: dict[Role, User]
) -> None:
    assert send(team[role], call, vial, passage0, tree).status_code == 200


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
@pytest.mark.parametrize("role", [r for r, allowed in HANDLERS.items() if allowed])
def test_technicians_and_up_handle_vials(
    *, call: Call, role: Role, vial: Vial, passage0: Passage, tree: Tree, team: dict[Role, User]
) -> None:
    before = snapshot()
    response = send(team[role], call, vial, passage0, tree)
    assert response.status_code == call.status, response.content
    assert snapshot() != before


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
def test_a_viewer_gets_403_before_the_input_is_read(
    call: Call, vial: Vial, passage0: Passage, viewer: User
) -> None:
    """Invalid input from a viewer is a 403, never a 400 that tells them what the form wants."""
    before = snapshot()
    url = call.url.format(vial=vial.public_id, passage=passage0.public_id)
    response = getattr(logged_in(viewer), call.method)(
        url, {"box": "x", "status": "x", "passage": "x"}, content_type="application/json"
    )
    assert_problem(response, 403, "permission_denied")
    assert snapshot() == before


@pytest.mark.parametrize("call", [c for c in CALLS if c.write], ids=lambda c: c.name)
def test_a_technician_elsewhere_is_only_what_they_are_here(
    call: Call, vial: Vial, passage0: Passage, tree: Tree, other_lab: Lab
) -> None:
    two_labs = member_of(other_lab, Role.TECHNICIAN, "two-labs")
    Membership.objects.create(user=two_labs, lab=vial.lab, role=Role.VIEWER)
    before = snapshot()
    assert_problem(send(two_labs, call, vial, passage0, tree), 403, "permission_denied")
    assert snapshot() == before


def test_outside_the_lab_invalid_input_is_still_404(outsider: User) -> None:
    for url in (PASSAGES_URL, BATCHES_URL):
        response = logged_in(outsider).post(url, {"passage": "x"}, content_type="application/json")
        assert_problem(response, 404, "not_found")


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
@pytest.mark.parametrize("url", [VIALS_URL + "{vial}/", PASSAGES_URL + "{passage}/"])
def test_nothing_is_changed_in_place_or_deleted(
    method: str, url: str, vial: Vial, passage0: Passage, manager: User
) -> None:
    response = getattr(logged_in(manager), method)(
        url.format(vial=vial.public_id, passage=passage0.public_id),
        {},
        content_type="application/json",
    )
    assert_problem(response, 405, "method_not_allowed")


def test_a_box_or_passage_of_another_lab_is_unknown_there(
    vial: Vial, technician: User, other_lab: Lab
) -> None:
    """The input fields resolve rows of every lab where the caller handles vials; the services
    keep the lab of the URL, with the same message as an unknown id."""
    Membership.objects.create(user=technician, lab=other_lab, role=Role.CURATOR)
    box_type = make_box_type("Other 9 x 9")
    with audit_context(channel=Channel.API, actor=technician):
        access = access_for(technician)
        freezer = storage.unit_create(
            access=access,
            lab=other_lab,
            data=storage.NewUnit(UnitKind.FREEZER, "F", max_risk_group=2),
        )
        box = storage.unit_create(
            access=access,
            lab=other_lab,
            data=storage.NewUnit(UnitKind.BOX, "B", freezer, box_type=box_type),
        )
    before = snapshot()
    response = logged_in(technician).post(
        f"{VIALS_URL}{vial.public_id}/place/",
        {"box": str(box.public_id), "row": 1, "col": 1},
        content_type="application/json",
    )
    body = assert_problem(response, 400, "does_not_exist", "box")
    assert body["errors"][0]["detail"] == "Invalid storage unit."
    assert snapshot() == before
