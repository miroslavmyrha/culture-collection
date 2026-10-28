"""Where the vials reserved for a request lie (#143): GET requests/<id>/vials/.

- every reader of the lab's vials gets them, in the order one walk through the storage picks
  them up: by the path of the box, each level by slot (none last), then name, then row and
  column; then the masked vials, then the vials in no box;
- a regulated vial's place is masked for every role, a holder of the location grant included,
  and its spot in the order tells nothing: a holder reveals it through the vial's reveal action;
- a request of another lab is 404, a shipped or cancelled request has no vial to pull.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from cultures.audit.context import audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.audit.registry import VIAL_LOCATION_REVEALED
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.deposits.tests.support import DUAL_USE
from cultures.distribution.models import DistributionRequest, Requester
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of, membership
from cultures.lineage import services as lineage
from cultures.lineage.models import Passage, Vial
from cultures.lineage.tests.support import pass_all, preserve
from cultures.storage.models import StorageUnit, UnitKind
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains.models import Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    LAB_URL,
    Supply,
    accept_mtas,
    approve,
    as_actor,
    reserved,
    ship,
    submit,
)

pytestmark = pytest.mark.django_db
ROLES = [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER]
REASON = "Dual-use inside the EU needs no licence."


def vials_url(request: DistributionRequest) -> str:
    return f"{LAB_URL}/requests/{request.public_id}/vials/"


def place(actor: User, vial: Vial, box: StorageUnit, row: int, col: int) -> None:
    with as_actor(actor):
        lineage.vial_place(access=access_for(actor), vial=vial, box=box, row=row, col=col)


def grant(lab: Lab, manager: User, user: User) -> None:
    with audit_context(channel=Channel.API, actor=manager, request_id="req-grant"):
        labs.location_grant_add(
            access=access_for(manager), lab=lab, membership=membership(user, lab), reason="pulls"
        )


@dataclass(frozen=True)
class Pull:
    request: DistributionRequest
    # The plain strain's vials in the order of the walk, the last one in no box.
    walk: list[Vial]
    masked: list[Vial]
    secret_box: StorageUnit


@pytest.fixture
def pull(
    *,
    curator: User,
    approver: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
    tree: Tree,
    make_unit: MakeUnit,
) -> Pull:
    """Five vials of a plain strain and two of a regulated one, all reserved for one request.

    Freezer A holds Rack 1 (slot 1, with Box 1 and the secret box), "Another rack" (slot 2,
    named before Rack 1, so the slot decides) and "Aa rack" without a slot (last, whatever its
    name). Freezer B holds a box directly. The regulated vials lie in the secret box in Rack 1,
    between the plain ones: their rows come after every shown place all the same."""
    plain = supply(vials=5)
    regulated = supply(mockia, restrictions=[DUAL_USE], vials=2)
    another = make_unit(UnitKind.RACK, "Another rack", tree.freezer, slot=2)
    box_2 = make_unit(UnitKind.BOX, "Box 2", another, slot=1)
    loose = make_unit(UnitKind.RACK, "Aa rack", tree.freezer)
    box_3 = make_unit(UnitKind.BOX, "Box 3", loose, slot=1)
    freezer_b = make_unit(UnitKind.FREEZER, "Freezer B", temperature_c=-80)
    box_b = make_unit(UnitKind.BOX, "Box B", freezer_b)
    secret_box = make_unit(UnitKind.BOX, "Box Hidden", tree.rack, slot=2)
    v = list(Vial.objects.filter(batch__strain=plain).order_by("seq"))
    place(curator, v[0], box_b, 1, 1)
    place(curator, v[1], tree.box, 2, 2)
    place(curator, v[2], tree.box, 1, 3)
    place(curator, v[3], box_3, 1, 1)
    place(curator, v[4], box_2, 5, 5)
    masked = list(Vial.objects.filter(batch__strain=regulated).order_by("seq"))
    place(curator, masked[0], secret_box, 1, 1)
    place(curator, masked[1], secret_box, 1, 2)
    # One plain vial more, never placed: the strain gives a sixth in a second batch.
    loose_vial = _sixth_vial(curator, plain)
    request = submit(curator, lab, requester, [(plain, 6), (regulated, 2)])
    accept_mtas(curator, request)
    request = approve(approver, request, REASON)
    assert set(reserved(request)) == {*v, loose_vial, *masked}
    # Box 1 A3, Box 1 B2, Another rack, Aa rack (no slot), Freezer B, no box.
    return Pull(request, [v[2], v[1], v[4], v[3], v[0], loose_vial], masked, secret_box)


def _sixth_vial(curator: User, strain: Strain) -> Vial:
    with as_actor(curator):
        batch = preserve(curator, Passage.objects.get(strain=strain, number=0), vial_count=1)
        pass_all(curator, batch)
        lineage.batch_release(access=access_for(curator), batch=batch, reason="checks passed")
    return Vial.objects.get(batch=batch)


def ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["public_id"] for row in rows]


def leaks(text: str, box: StorageUnit) -> bool:
    return str(box.public_id) in text or box.name in text


@pytest.mark.parametrize("granted", [False, True], ids=["without", "with the grant"])
@pytest.mark.parametrize("role", ROLES)
def test_every_reader_gets_the_walk_and_no_regulated_place(
    *,
    role: Role,
    granted: bool,
    team: dict[Role, User],
    manager: User,
    lab: Lab,
    pull: Pull,
) -> None:
    reader = team[role]
    if granted:
        grant(lab, manager, reader)
    response = logged_in(reader).get(vials_url(pull.request))
    assert response.status_code == 200, response.content
    assert not leaks(response.content.decode(), pull.secret_box)
    rows = response.json()
    walk = [str(v.public_id) for v in pull.walk]
    masked = [str(v.public_id) for v in pull.masked]
    # The placed plain vials, then the masked ones, then the one in no box.
    assert ids(rows) == walk[:-1] + masked + walk[-1:]
    for row in rows[5:7]:
        assert (row["location"], row["location_masked"], row["placed"], row["can_reveal"]) == (
            None,
            True,
            True,
            granted,
        )
    assert [row["location"]["path"] + [row["location"]["label"]] for row in rows[:5]] == [
        ["Freezer A", "Rack 1", "Box 1", "A3"],
        ["Freezer A", "Rack 1", "Box 1", "B2"],
        ["Freezer A", "Another rack", "Box 2", "E5"],
        ["Freezer A", "Aa rack", "Box 3", "A1"],
        ["Freezer B", "Box B", "A1"],
    ]
    assert all(not row["location_masked"] and not row["can_reveal"] for row in rows[:5])
    assert (rows[7]["placed"], rows[7]["location"], rows[7]["location_masked"]) == (
        False,
        None,
        False,
    )
    assert rows[0]["label"].endswith(" / 1 / 3")


def test_a_holder_reveals_a_vial_of_the_list_and_the_reveal_is_recorded(
    *, team: dict[Role, User], manager: User, lab: Lab, pull: Pull
) -> None:
    technician = team[Role.TECHNICIAN]
    grant(lab, manager, technician)
    client = logged_in(technician)
    row = client.get(vials_url(pull.request)).json()[5]
    assert row["can_reveal"]
    events = AuditEvent.objects.filter(event_type=VIAL_LOCATION_REVEALED.code).count()
    response = client.post(f"{LAB_URL}/vials/{row['public_id']}/reveal-location/")
    assert response.status_code == 200, response.content
    assert response.json()["location"]["path"] == ["Freezer A", "Rack 1", "Box Hidden"]
    assert response["Cache-Control"] == "no-store"
    assert AuditEvent.objects.filter(event_type=VIAL_LOCATION_REVEALED.code).count() == events + 1
    # The list after the reveal is masked as before.
    assert not leaks(client.get(vials_url(pull.request)).content.decode(), pull.secret_box)


def test_without_the_grant_a_vial_of_the_list_is_not_revealed(
    *, team: dict[Role, User], pull: Pull
) -> None:
    client = logged_in(team[Role.MANAGER])
    row = client.get(vials_url(pull.request)).json()[5]
    assert not row["can_reveal"]
    response = client.post(f"{LAB_URL}/vials/{row['public_id']}/reveal-location/")
    assert_problem(response, 403, "location_grant_required")
    assert not leaks(response.content.decode(), pull.secret_box)


def test_a_request_of_another_lab_is_404_from_this_lab(
    *, other_lab: Lab, outsider: User, lab: Lab, pull: Pull
) -> None:
    """A manager elsewhere and a viewer here reads this lab's request; the other lab's URL with
    this request's id finds nothing."""
    Membership.objects.create(user=outsider, lab=lab, role=Role.VIEWER)
    client = logged_in(outsider)
    assert client.get(vials_url(pull.request)).status_code == 200
    url = f"/api/v1/labs/{other_lab.public_id}/requests/{pull.request.public_id}/vials/"
    assert_problem(client.get(url), 404, "not_found")


def test_a_submitted_and_a_shipped_request_have_no_vial_to_pull(
    *, curator: User, lab: Lab, requester: Requester, supply: Supply
) -> None:
    strain = supply()
    request = submit(curator, lab, requester, [(strain, 1)])
    client = logged_in(curator)
    assert client.get(vials_url(request)).json() == []
    accept_mtas(curator, request)
    approve(curator, request)
    assert len(client.get(vials_url(request)).json()) == 1
    ship(curator, request)
    assert client.get(vials_url(request)).json() == []


@pytest.mark.parametrize("count", [1, 6])
def test_the_query_count_is_exact_and_flat(
    *,
    count: int,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    tree: Tree,
    make_unit: MakeUnit,
    query_baseline: QueryBaseline,
) -> None:
    """Session, user, memberships, the lab, the request, the vials, their placements with the
    boxes, the box paths, the units of the walk and the location grant."""
    strain = supply(vials=count)
    for i, vial in enumerate(Vial.objects.filter(batch__strain=strain).order_by("seq")):
        box = make_unit(UnitKind.BOX, f"Box {i + 10}", tree.rack, slot=i + 2)
        place(curator, vial, box, 1, 1)
    request = submit(curator, lab, requester, [(strain, count)])
    accept_mtas(curator, request)
    approve(curator, request)
    technician = member_of(lab, Role.TECHNICIAN, "puller")
    client = logged_in(technician)
    with query_baseline("request_vials"):
        rows = client.get(vials_url(request)).json()
    assert len(rows) == count
