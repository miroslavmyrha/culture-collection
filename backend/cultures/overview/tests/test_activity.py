"""Recent activity on Home (#69): which events a person reads, and what a line may say. Never more
than the person may read on the subject's own page, never where a regulated strain is, never a
name."""

import json

import pytest

from cultures.audit.models import AuditEvent
from cultures.audit.registry import EVENT_TYPES
from cultures.core.testing import logged_in
from cultures.deposits.tests.support import DUAL_USE, MakeDeposit
from cultures.distribution.models import Requester
from cultures.distribution.tests.support import (
    MakeRequester,
    Supply,
    accept_mtas,
    approve,
    as_actor,
    submit,
)
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of, membership
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch, Passage
from cultures.lineage.tests.support import preserve, vials_of
from cultures.overview.activity import ACTIVITY_LIMIT, HIDDEN, SHOWN
from cultures.storage.tests.conftest import Tree
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import ACTIVITY_URL, lines

pytestmark = pytest.mark.django_db


def summaries(user: User) -> list[str]:
    return [line["summary"] for line in lines(user)]


def test_every_event_type_is_shown_or_hidden_with_a_reason() -> None:
    """A new event type needs a decision: who reads it on Home, or why nobody does."""
    assert not set(SHOWN) & set(HIDDEN)
    assert set(SHOWN) | set(HIDDEN) == set(EVENT_TYPES)
    assert all(reason.strip() for reason in HIDDEN.values())


def test_a_deposit_is_read_by_those_who_may_open_it(
    make_deposit: MakeDeposit, exempli: Taxon, team: dict[Role, User]
) -> None:
    """The deposit's events need deposits.view; the strain it became is the viewers' too."""
    deposit = make_deposit("accepted", taxon=exempli, name_as_received="Testella exempli A1")
    assert deposit.strain is not None
    number = deposit.strain.accession_number
    for role, user in team.items():
        seen = summaries(user)
        assert f"accessioned {number}" in seen, role
        deposit_lines = [s for s in seen if s.endswith("deposit Testella exempli A1")]
        if role in (Role.CURATOR, Role.MANAGER):
            assert deposit_lines == [
                "accepted deposit Testella exempli A1",
                "started checking deposit Testella exempli A1",
                "received deposit Testella exempli A1",
            ], role
        else:
            assert deposit_lines == [], role
    received = next(
        line for line in lines(team[Role.CURATOR]) if line["summary"].startswith("received")
    )
    assert (received["target"], received["target_id"]) == ("deposit", str(deposit.public_id))


def test_a_requester_is_read_by_those_who_read_requesters(
    make_requester: MakeRequester, team: dict[Role, User]
) -> None:
    make_requester()
    for role, user in team.items():
        assert ("added a requester" in summaries(user)) == (role in (Role.CURATOR, Role.MANAGER)), (
            role
        )


def test_a_placement_says_which_vial_never_where(
    supply: Supply, mockia: Taxon, tree: Tree, manager: User, curator: User
) -> None:
    """A vial of a regulated strain placed by hand: the event holds the box and position, the
    line holds the label alone, for every role, a holder of the location grant included."""
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
    event = AuditEvent.objects.get(event_type="vial_placed")
    where = json.dumps(event.changes["location"][1])
    assert '"row": 3' in where  # the event knows where; the line must not
    body = logged_in(manager).get(ACTIVITY_URL).content.decode()
    line = next(line for line in lines(manager) if line["summary"].startswith("placed vial"))
    assert line["summary"] == f"placed vial {strain.accession_number} / 1 / 1"
    assert (line["target"], line["target_id"]) == ("strain", str(strain.public_id))
    placements = [line for line in lines(manager) if "vial" in line["summary"]]
    assert all(line["target"] == "strain" for line in placements)
    assert not [
        line for line in placements if "Box 1" in line["summary"] or "C4" in line["summary"]
    ]
    assert '"row"' not in body
    assert set(line) == {
        "occurred_at",
        "lab",
        "lab_code",
        "actor",
        "summary",
        "target",
        "target_id",
    }


def test_a_reveal_is_never_a_line(
    supply: Supply, mockia: Taxon, tree: Tree, manager: User, curator: User
) -> None:
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
        lineage.vial_place(access=access_for(curator), vial=vial, box=tree.box, row=1, col=1)
    with as_actor(manager):
        lineage.vial_reveal_location(access=access_for(manager), vial=vial)
    assert AuditEvent.objects.filter(event_type="vial_location_revealed").exists()
    assert not [s for s in summaries(manager) if "reveal" in s]


def test_a_location_grant_is_read_by_managers_only(lab: Lab, team: dict[Role, User]) -> None:
    manager = team[Role.MANAGER]
    with as_actor(manager):
        labs.location_grant_add(
            access=access_for(manager),
            lab=lab,
            membership=membership(team[Role.VIEWER], lab),
            reason="Register.",
        )
    for role, user in team.items():
        shown = "let a member see regulated locations" in summaries(user)
        assert shown == (role == Role.MANAGER), role


def test_lines_name_the_actor_by_label_and_the_reader_as_you(
    supply: Supply, team: dict[Role, User], curator: User
) -> None:
    """The supply is made by the curator, its MTA published by the manager."""
    supply(release=False)
    viewer, manager = team[Role.VIEWER], team[Role.MANAGER]
    assert {line["actor"] for line in lines(curator)} == {"you", f"user:{manager.public_id}"}
    # The MTA's event is a deposits event: a viewer does not read it.
    assert {line["actor"] for line in lines(viewer)} == {f"user:{curator.public_id}"}
    body = logged_in(viewer).get(ACTIVITY_URL).content.decode()
    assert curator.username not in body
    assert manager.username not in body


def test_a_write_of_many_vials_is_one_line(supply: Supply, curator: User, viewer: User) -> None:
    strain = supply(release=False, vials=4)
    seen = summaries(viewer)
    assert f"added 4 vials of {strain.accession_number}" in seen
    assert not [s for s in seen if s.startswith("added vial")]


def test_a_status_change_says_the_new_status(supply: Supply, viewer: User) -> None:
    strain = supply()  # released after its checks
    seen = summaries(viewer)
    assert f"set {strain.accession_number} batch 1 to released" in seen
    assert f"recorded a check of {strain.accession_number} batch 1" in seen


def test_a_request_line_links_to_its_request(
    supply: Supply, lab: Lab, requester: Requester, curator: User, viewer: User
) -> None:
    request = submit(curator, lab, requester, [(supply(), 1)])
    accept_mtas(curator, request)
    approve(curator, request)
    by_summary = {line["summary"]: line for line in lines(viewer)}
    for summary in (
        f"approved request {request.label}",
        f"reserved vials for request {request.label}",
        f"asked for vials in request {request.label}",
        f"entered request {request.label}",
    ):
        assert (by_summary[summary]["target"], by_summary[summary]["target_id"]) == (
            "request",
            str(request.public_id),
        )
    # The acceptance names its signer: read by those who read requesters, not by a viewer.
    assert f"recorded an acceptance of the MTA for request {request.label}" not in by_summary
    assert f"recorded an acceptance of the MTA for request {request.label}" in summaries(curator)


def test_another_labs_events_never_show(
    make_deposit: MakeDeposit, exempli: Taxon, outsider: User, curator: User
) -> None:
    make_deposit("accepted", taxon=exempli)
    assert lines(outsider) == []
    assert {line["lab_code"] for line in lines(curator)} == {"MYC"}


def test_a_person_in_two_labs_reads_each_lab_by_its_own_role(
    make_deposit: MakeDeposit, exempli: Taxon, lab: Lab, other_lab: Lab
) -> None:
    """Curator in one lab, viewer in the other: the other lab's deposit events stay out, its
    strain events come in."""
    person = member_of(other_lab, Role.CURATOR, "two-labs")
    Membership.objects.create(user=person, lab=lab, role=Role.VIEWER)
    deposit = make_deposit("accepted", taxon=exempli, name_as_received="Testella exempli A2")
    assert deposit.strain is not None
    seen = summaries(person)
    assert f"accessioned {deposit.strain.accession_number}" in seen
    assert not [s for s in seen if "deposit" in s]


def test_the_latest_twenty_come_newest_first(passage: Passage, curator: User, viewer: User) -> None:
    with as_actor(curator):
        for _ in range(ACTIVITY_LIMIT + 1):
            preserve(curator, passage, vial_count=1)
    seen = lines(viewer)
    assert len(seen) == ACTIVITY_LIMIT
    numbers = [s["summary"] for s in seen if s["summary"].startswith("preserved")]
    assert numbers[0].endswith(f"batch {ACTIVITY_LIMIT + 2}")  # the supply's own batch is 1
    times = [s["occurred_at"] for s in seen]
    assert times == sorted(times, reverse=True)


@pytest.fixture
def passage(supply: Supply) -> Passage:
    return Passage.objects.get(strain=supply(release=False), number=0)
