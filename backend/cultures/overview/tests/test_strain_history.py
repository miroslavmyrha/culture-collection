"""A strain's history on its own page (#19): the events whose timeline root is the strain, read
under the rules of the activity on Home (activity.events), one line each, newest first, a page
at a time. Never more than Home would show the person, never another strain's events, never
where a regulated strain is."""

import json
from typing import Any

import pytest

from cultures.audit.models import AuditEvent
from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.deposits.tests.support import DUAL_USE, MakeDeposit
from cultures.distribution.models import Requester
from cultures.distribution.tests.support import Supply, accept_mtas, approve, as_actor, submit
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import membership
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, Passage
from cultures.lineage.tests.support import preserve, vials_of
from cultures.storage.tests.conftest import Tree
from cultures.strains.models import Strain
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import lines as home_lines

pytestmark = pytest.mark.django_db

LAB_URL = "/api/v1/labs/00000000-0000-4000-8000-00000000000a"


def history_url(strain: Strain) -> str:
    return f"{LAB_URL}/strains/{strain.public_id}/history/"


def page(user: User, strain: Strain, **params: Any) -> dict[str, Any]:
    response = logged_in(user).get(history_url(strain), params)
    assert response.status_code == 200, response.content
    data: dict[str, Any] = response.json()
    return data


def summaries(user: User, strain: Strain) -> list[str]:
    return [line["summary"] for line in page(user, strain, limit=200)["results"]]


@pytest.fixture
def passage(supply: Supply) -> Passage:
    return Passage.objects.get(strain=supply(release=False), number=0)


def test_a_line_is_shown_exactly_where_home_shows_it(
    make_deposit: MakeDeposit, exempli: Taxon, supply: Supply, team: dict[Role, User]
) -> None:
    """For every role: the strain's history is Home's activity narrowed to the strain. The
    deposit's lines need deposits.view on both, the strain's lines are the viewers' too."""
    deposit = make_deposit("accepted", taxon=exempli, name_as_received="Testella exempli H1")
    strain = deposit.strain
    assert strain is not None
    supply(release=False)  # another strain's events: on Home, not in this history
    for role, user in team.items():
        mine = summaries(user, strain)
        about_it = [
            line["summary"]
            for line in home_lines(user)
            if line["target_id"] in (str(strain.public_id), str(deposit.public_id))
        ]
        assert f"accessioned {strain.accession_number}" in mine, role
        accepted = "accepted deposit Testella exempli H1" in mine
        assert accepted == (role in (Role.CURATOR, Role.MANAGER)), role
        # Received and checked before the strain existed: Home's lines, not the strain's.
        assert set(mine) <= set(about_it), role
        assert [s for s in about_it if s not in mine] == [
            s for s in about_it if s.startswith(("received", "started checking"))
        ], role


def test_another_strains_events_never_show(supply: Supply, viewer: User) -> None:
    one = supply(release=False, vials=2)
    other = supply(release=False, vials=3)
    assert other.accession_number is not None
    seen = summaries(viewer, one)
    assert seen
    assert not [s for s in seen if other.accession_number in s]
    events = AuditEvent.objects.filter(strain_id=one.public_id).count()
    assert page(viewer, one)["count"] <= events


def test_a_placement_says_which_vial_never_where(
    *, supply: Supply, mockia: Taxon, tree: Tree, manager: User, curator: User, viewer: User
) -> None:
    """A regulated strain's vial placed by hand: the event holds the box and position, the
    history holds the label alone, for a holder of the location grant too."""
    strain = supply(mockia, restrictions=[DUAL_USE], release=False)
    vial = vials_of(Batch.objects.get(strain=strain))[0]
    with as_actor(manager):
        labs.location_grant_add(
            access=access_for(manager),
            lab=strain.lab,
            membership=membership(manager, strain.lab),
            reason="Register.",
        )
    with as_actor(curator):
        lineage.vial_place(access=access_for(curator), vial=vial, box=tree.box, row=3, col=4)
    with as_actor(manager):
        lineage.vial_reveal_location(access=access_for(manager), vial=vial)
    event = AuditEvent.objects.get(event_type="vial_placed")
    assert '"row": 3' in json.dumps(event.changes["location"][1])  # the event knows where
    for user in (manager, viewer):
        body = logged_in(user).get(history_url(strain), {"limit": 200}).content.decode()
        assert f"placed vial {strain.accession_number} / 1 / 1" in summaries(user, strain)
        assert '"row"' not in body
        assert tree.box.name not in body
        assert "C4" not in body
        assert "reveal" not in body
    line = page(manager, strain)["results"][0]
    assert set(line) == {"occurred_at", "actor", "summary", "target", "target_id"}


def test_request_lines_follow_the_request_rules(
    supply: Supply, lab: Lab, requester: Requester, curator: User, viewer: User
) -> None:
    strain = supply()
    request = submit(curator, lab, requester, [(strain, 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    seen = summaries(viewer, strain)
    assert f"asked for vials in request {request.label}" in seen
    assert f"reserved vials for request {request.label}" in seen
    # The acceptance names its signer: read by those who read requesters, not by a viewer.
    acceptance = f"recorded an acceptance of the MTA for request {request.label}"
    assert acceptance not in seen
    by_line = {line["summary"]: line for line in page(viewer, strain, limit=200)["results"]}
    assert by_line[f"asked for vials in request {request.label}"]["target_id"] == str(
        request.public_id
    )


def test_a_location_grant_is_never_in_a_strains_history(
    supply: Supply, lab: Lab, team: dict[Role, User]
) -> None:
    strain = supply(release=False)
    manager = team[Role.MANAGER]
    with as_actor(manager):
        labs.location_grant_add(
            access=access_for(manager),
            lab=lab,
            membership=membership(team[Role.VIEWER], lab),
            reason="Register.",
        )
    assert not [s for s in summaries(manager, strain) if "regulated locations" in s]


def test_pages_cover_every_line_once_newest_first(passage: Passage, curator: User) -> None:
    with as_actor(curator):
        for _ in range(7):
            preserve(curator, passage, vial_count=1)
    strain = passage.strain
    every = page(curator, strain, limit=200)
    total = every["count"]
    assert total == len(every["results"]) > 7
    seen: list[dict[str, Any]] = []
    for offset in range(0, total, 3):
        part = page(curator, strain, limit=3, offset=offset)
        assert part["count"] == total
        seen += part["results"]
    assert seen == every["results"]
    times = [line["occurred_at"] for line in seen]
    assert times == sorted(times, reverse=True)
    assert seen[0]["summary"] == f"added 1 vials of {strain.accession_number}"
    assert page(curator, strain, limit=1000)["results"] == every["results"][:200]


def test_the_page_size_is_capped(passage: Passage, curator: User) -> None:
    with as_actor(curator):
        for _ in range(101):
            preserve(curator, passage, vial_count=1)
    data = page(curator, passage.strain, limit=1000)
    assert data["count"] > 200
    assert len(data["results"]) == 200


def test_outside_the_lab_is_not_found(supply: Supply, outsider: User, other_lab: Lab) -> None:
    strain = supply(release=False)
    assert_problem(logged_in(outsider).get(history_url(strain)), 404, "not_found")
    assert logged_in(None).get(history_url(strain)).status_code == 401
    # A member of both labs who asks for the strain under the other lab's URL.
    Membership.objects.create(user=outsider, lab=strain.lab, role=Role.VIEWER)
    other = f"/api/v1/labs/{other_lab.public_id}/strains/{strain.public_id}/history/"
    assert_problem(logged_in(outsider).get(other), 404, "not_found")


@pytest.mark.parametrize("batches", [1, 20])  # one key for both sizes: the count must not grow
def test_the_query_count_is_exact_and_flat(
    batches: int, passage: Passage, curator: User, viewer: User, query_baseline: QueryBaseline
) -> None:
    with as_actor(curator):
        for _ in range(batches):
            preserve(curator, passage, vial_count=2)
    client, url = logged_in(viewer), history_url(passage.strain)
    # Session, user, memberships, the lab, the strain, the count, the page with every label.
    with query_baseline("strain_history") as captured:
        response = client.get(url)
    assert response.json()["count"] > batches
    events = [q["sql"] for q in captured.captured_queries if "audit_auditevent" in q["sql"]]
    assert events and all('"audit_auditevent"."lab_id" IN (' in sql for sql in events)
