"""Where a regulated strain is stored (ADR 0009, amendment of 2026-10-19), at the API, for
every role with and without the location grant:
- no list and no answer but the reveal carries the location of a regulated vial;
- only a holder of the grant reveals it, and each reveal writes its event before the
  answer: a failed write is a failed answer without the location;
- a vial of a strain without restrictions shows its place to every reader.
"""

import json
from typing import Any

import pytest
from django.db import connection

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.core.testing import assert_problem, logged_in
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab, LocationGrant, Membership
from cultures.labs.permissions import GRANTS, Perm, Role
from cultures.labs.tests.conftest import member_of, membership
from cultures.lineage.models import Passage, Vial
from cultures.lineage.services import is_regulated, location_of
from cultures.storage.models import StorageUnit, UnitKind
from cultures.storage.tests.conftest import MakeUnit, Tree
from cultures.strains import services as strains
from cultures.strains.models import Strain
from cultures.strains.tests.conftest import GMO, end_restriction
from cultures.users import services as users
from cultures.users.models import User

from .support import VIALS_URL, MakeBatch, vials_of

pytestmark = pytest.mark.django_db
ROLES = [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR, Role.MANAGER]


@pytest.fixture
def secret_box(tree: Tree, make_unit: MakeUnit) -> StorageUnit:
    """A box only regulated vials are in: its name and id must never reach a list."""
    return make_unit(UnitKind.BOX, "Box Hidden", tree.rack, slot=2)


@pytest.fixture
def masked(regulated: Strain, make_batch: MakeBatch, secret_box: StorageUnit) -> list[Vial]:
    passage = Passage.objects.get(strain=regulated, number=0)
    return vials_of(make_batch(passage, vial_count=2, box=secret_box))


@pytest.fixture
def plain(passage0: Passage, make_batch: MakeBatch, tree: Tree) -> Vial:
    return vials_of(make_batch(passage0, vial_count=1, box=tree.box))[0]


def grant(lab: Lab, manager: User, user: User) -> LocationGrant:
    with audit_context(channel=Channel.API, actor=manager, request_id="req-grant"):
        return labs.location_grant_add(
            access=access_for(manager), lab=lab, membership=membership(user, lab), reason="register"
        )


def leaks(text: str, box: StorageUnit) -> bool:
    return str(box.public_id) in text or box.name in text


@pytest.mark.parametrize("granted", [False, True], ids=["without", "with the grant"])
@pytest.mark.parametrize("role", ROLES)
def test_lists_and_details_never_carry_a_regulated_location(
    *,
    role: Role,
    granted: bool,
    team: dict[Role, User],
    manager: User,
    lab: Lab,
    masked: list[Vial],
    plain: Vial,
    secret_box: StorageUnit,
    tree: Tree,
) -> None:
    reader = team[role]
    if granted:
        grant(lab, manager, reader)
    client = logged_in(reader)
    listed = client.get(VIALS_URL)
    assert listed.status_code == 200
    assert not leaks(listed.content.decode(), secret_box)
    rows = {row["public_id"]: row for row in listed.json()["results"]}
    for vial in masked:
        row = rows[str(vial.public_id)]
        assert (row["location"], row["location_masked"], row["placed"], row["can_reveal"]) == (
            None,
            True,
            True,
            granted,
        )
        detail = client.get(f"{VIALS_URL}{vial.public_id}/")
        assert not leaks(detail.content.decode(), secret_box)
        assert (detail.json()["location"], detail.json()["can_reveal"]) == (None, granted)
    shown = rows[str(plain.public_id)]
    assert (shown["location_masked"], shown["can_reveal"]) == (False, False)
    assert shown["location"] == {
        "box": str(tree.box.public_id),
        "box_name": "Box 1",
        "path": ["Freezer A", "Rack 1", "Box 1"],
        "row": 1,
        "col": 1,
        "label": "A1",
    }


@pytest.mark.parametrize("role", ROLES)
def test_without_the_grant_no_role_reveals(
    role: Role, team: dict[Role, User], masked: list[Vial], secret_box: StorageUnit
) -> None:
    events = AuditEvent.objects.count()
    response = logged_in(team[role]).post(f"{VIALS_URL}{masked[0].public_id}/reveal-location/")
    assert_problem(response, 403, "location_grant_required")
    assert not leaks(response.content.decode(), secret_box)
    assert AuditEvent.objects.count() == events


@pytest.mark.parametrize("role", ROLES)
def test_a_holder_of_the_grant_reveals_and_the_reveal_is_recorded(
    *,
    role: Role,
    team: dict[Role, User],
    manager: User,
    lab: Lab,
    masked: list[Vial],
    regulated: Strain,
    secret_box: StorageUnit,
) -> None:
    reader = team[role]
    grant(lab, manager, reader)
    events = AuditEvent.objects.count()
    response = logged_in(reader).post(f"{VIALS_URL}{masked[1].public_id}/reveal-location/")
    assert response.status_code == 200, response.content
    assert response["Cache-Control"] == "no-store"
    assert response.json() == {
        "location": {
            "box": str(secret_box.public_id),
            "box_name": "Box Hidden",
            "path": ["Freezer A", "Rack 1", "Box Hidden"],
            "row": 1,
            "col": 2,
            "label": "A2",
        }
    }
    assert AuditEvent.objects.count() == events + 1
    event = AuditEvent.objects.order_by("-pk").first()
    assert event is not None
    assert (event.event_type, event.actor, event.subject_type, event.subject_id) == (
        "vial_location_revealed",
        reader,
        "vial",
        masked[1].public_id,
    )
    assert (event.strain_id, event.lab_id, event.request_id) == (
        regulated.public_id,
        lab.pk,
        response["X-Request-ID"],
    )
    assert event.changes == {}  # who and which vial, never where


def test_a_plain_vial_is_revealed_by_anyone_without_an_event(viewer: User, plain: Vial) -> None:
    events = AuditEvent.objects.count()
    response = logged_in(viewer).post(f"{VIALS_URL}{plain.public_id}/reveal-location/")
    assert response.json()["location"]["label"] == "A1"
    assert AuditEvent.objects.count() == events


def test_a_failed_event_write_fails_the_reveal_without_the_location(
    keeper: User, masked: list[Vial], secret_box: StorageUnit, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the audit table is not writable")

    monkeypatch.setattr(AuditEvent, "save", broken)
    client = logged_in(keeper)
    client.raise_request_exception = False
    response = client.post(f"{VIALS_URL}{masked[0].public_id}/reveal-location/")
    assert response.status_code == 500
    assert not leaks(response.content.decode(), secret_box)


@pytest.mark.slow
@pytest.mark.django_db(transaction=True)
def test_the_reveal_is_committed_before_the_location_is_read(
    keeper: User, masked: list[Vial], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[bool, int]] = []

    def spy(vial: Vial) -> Any:
        seen.append(
            (
                connection.in_atomic_block,
                AuditEvent.objects.filter(event_type="vial_location_revealed").count(),
            )
        )
        return location_of(vial)

    monkeypatch.setattr("cultures.lineage.services.location_of", spy)
    response = logged_in(keeper).post(f"{VIALS_URL}{masked[0].public_id}/reveal-location/")
    assert response.status_code == 200
    assert seen == [(False, 1)]  # outside any transaction, the event already there


def test_a_technician_without_the_grant_places_a_regulated_vial_and_sees_it_masked(
    technician: User, masked: list[Vial], secret_box: StorageUnit, tree: Tree
) -> None:
    response = logged_in(technician).post(
        f"{VIALS_URL}{masked[0].public_id}/place/",
        {"box": str(tree.box.public_id), "row": 9, "col": 9},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["location"], body["location_masked"]) == (None, True)
    assert str(tree.box.public_id) not in response.content.decode()
    status = logged_in(technician).post(
        f"{VIALS_URL}{masked[0].public_id}/status/",
        {"status": "quarantined", "reason": "check"},
        content_type="application/json",
    )
    assert (status.json()["location"], status.json()["location_masked"]) == (None, True)


def test_a_revoked_grant_reveals_nothing(
    keeper: User, manager: User, lab: Lab, masked: list[Vial]
) -> None:
    url = f"{VIALS_URL}{masked[0].public_id}/reveal-location/"
    assert logged_in(keeper).post(url).status_code == 200
    with audit_context(channel=Channel.API, actor=manager):
        labs.location_grant_revoke(
            access=access_for(manager),
            grant=LocationGrant.objects.get(user=keeper, revoked_at__isnull=True),
            reason="left the project",
        )
    assert_problem(logged_in(keeper).post(url), 403, "location_grant_required")
    assert logged_in(keeper).get(f"{VIALS_URL}{masked[0].public_id}/").json()["can_reveal"] is False


def test_a_member_who_leaves_loses_the_grant_for_good(
    keeper: User, manager: User, lab: Lab, masked: list[Vial]
) -> None:
    with audit_context(channel=Channel.API, actor=manager):
        labs.member_remove(access=access_for(manager), membership=membership(keeper, lab))
        labs.member_add(access=access_for(manager), lab=lab, user=keeper, role=Role.VIEWER)
    url = f"{VIALS_URL}{masked[0].public_id}/reveal-location/"
    assert_problem(logged_in(keeper).post(url), 403, "location_grant_required")
    revoked = LocationGrant.objects.get(user=keeper)
    assert (revoked.revoke_reason, revoked.revoked_by) == ("The member left the lab.", manager)


def test_a_deactivated_holder_reveals_nothing(keeper: User, masked: list[Vial], lab: Lab) -> None:
    """Deactivated after the grant: the account signs in nowhere, and the grant would not count
    if it did."""
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:t"
    ):
        users.user_deactivate(user=keeper, reason="left")
    assert labs.holds_location_grant(lab_id=lab.pk, user=keeper) is False
    assert LocationGrant.objects.filter(user=keeper, revoked_at__isnull=True).exists()


def test_no_role_implies_the_grant(team: dict[Role, User], lab: Lab, masked: list[Vial]) -> None:
    assert not any("location" in perm.value for perm in Perm)
    assert not any("location" in perm for perms in GRANTS.values() for perm in perms)
    assert [labs.holds_location_grant(lab_id=lab.pk, user=u) for u in team.values()] == [False] * 4


def test_a_grant_in_another_lab_counts_only_there(
    keeper: User, other_lab: Lab, masked: list[Vial]
) -> None:
    Membership.objects.create(user=keeper, lab=other_lab, role=Role.VIEWER)
    assert labs.holds_location_grant(lab_id=other_lab.pk, user=keeper) is False
    body = json.loads(logged_in(keeper).get(VIALS_URL).content)
    assert all(row["can_reveal"] for row in body["results"])


def test_moving_a_regulated_vial_shows_neither_where_it_was_nor_where_it_went(
    technician: User,
    masked: list[Vial],
    secret_box: StorageUnit,
    tree: Tree,
    plain: Vial,
) -> None:
    """A move by someone without the grant: no answer names the old place or the new one, a
    refused move neither (the position of another vial is taken)."""
    client = logged_in(technician)
    url = f"{VIALS_URL}{masked[0].public_id}/place/"

    def hides(response: Any) -> None:
        text = response.content.decode()
        assert not leaks(text, secret_box), text
        assert str(tree.box.public_id) not in text and "Box 1" not in text, text
        assert '"row"' not in text and '"col"' not in text, text

    taken = client.post(
        url, {"box": str(tree.box.public_id), "row": 1, "col": 1}, content_type="application/json"
    )
    assert_problem(taken, 409, "position_taken")  # the plain vial is in A1
    hides(taken)
    moved = client.post(
        url, {"box": str(tree.box.public_id), "row": 5, "col": 5}, content_type="application/json"
    )
    assert moved.status_code == 200
    hides(moved)
    assert moved.json()["location"] is None
    again = client.post(
        url, {"box": str(tree.box.public_id), "row": 5, "col": 5}, content_type="application/json"
    )
    hides(again)
    hides(client.get(f"{VIALS_URL}{masked[0].public_id}/"))


def end_restrictions(curator: User, strain: Strain, keep: int = 0) -> None:
    """Ends the strain's active restrictions through the services, all but the last `keep`: the
    curator proposes, a manager of the lab confirms (#105)."""
    active = list(strain.restrictions.filter(ended_at__isnull=True).order_by("pk"))
    confirmer = User.objects.filter(
        memberships__lab=strain.lab, memberships__role=Role.MANAGER
    ).exclude(pk=curator.pk).first() or member_of(strain.lab, Role.MANAGER, "confirmer")
    for restriction in active[: len(active) - keep]:
        end_restriction(restriction, proposer=curator, confirmer=confirmer, reason="delisted")


@pytest.mark.parametrize("role", ROLES)
def test_a_strain_whose_last_restriction_ended_shows_its_places_again(
    *,
    role: Role,
    team: dict[Role, User],
    curator: User,
    keeper: User,
    regulated: Strain,
    masked: list[Vial],
    secret_box: StorageUnit,
    tree: Tree,
) -> None:
    end_restrictions(curator, regulated)
    assert is_regulated(regulated) is False
    for reader in (team[role], keeper):
        client = logged_in(reader)
        rows = {r["public_id"]: r for r in client.get(VIALS_URL).json()["results"]}
        detail = client.get(f"{VIALS_URL}{masked[0].public_id}/").json()
        for shown in (rows[str(masked[0].public_id)], detail):
            assert (shown["location_masked"], shown["can_reveal"]) == (False, False)
            assert shown["location"]["box"] == str(secret_box.public_id)
            assert shown["location"]["label"] == "A1"


@pytest.mark.parametrize("role", [Role.TECHNICIAN, Role.CURATOR, Role.MANAGER])
def test_after_the_last_restriction_ended_the_write_answers_show_the_place(
    *,
    role: Role,
    team: dict[Role, User],
    curator: User,
    regulated: Strain,
    masked: list[Vial],
    tree: Tree,
) -> None:
    end_restrictions(curator, regulated)
    writer = logged_in(team[role])
    placed = writer.post(
        f"{VIALS_URL}{masked[1].public_id}/place/",
        {"box": str(tree.box.public_id), "row": 7, "col": 7},
        content_type="application/json",
    ).json()
    assert (placed["location"]["label"], placed["location_masked"]) == ("G7", False)
    status = writer.post(
        f"{VIALS_URL}{masked[0].public_id}/status/",
        {"status": "quarantined", "reason": "check"},
        content_type="application/json",
    ).json()
    assert (status["location"]["label"], status["location_masked"], status["can_reveal"]) == (
        "A1",
        False,
        False,
    )
    # A reveal now needs no grant and records nothing.
    events = AuditEvent.objects.count()
    revealed = writer.post(f"{VIALS_URL}{masked[0].public_id}/reveal-location/")
    assert revealed.json()["location"]["label"] == "A1"
    assert AuditEvent.objects.count() == events


@pytest.mark.parametrize("role", ROLES)
def test_one_ended_and_one_active_restriction_stay_masked(
    *,
    role: Role,
    team: dict[Role, User],
    curator: User,
    regulated: Strain,
    masked: list[Vial],
    secret_box: StorageUnit,
) -> None:
    with audit_context(channel=Channel.API, actor=curator, request_id="req-add"):
        strains.strain_restriction_add(
            access=access_for(curator), strain=regulated, restriction=GMO, reason="listed"
        )
    end_restrictions(curator, regulated, keep=1)  # the dual-use entry ends, the GMO stays
    assert regulated.restrictions.filter(ended_at__isnull=True).count() == 1
    assert is_regulated(regulated) is True
    client = logged_in(team[role])
    listed = client.get(VIALS_URL)
    detail = client.get(f"{VIALS_URL}{masked[0].public_id}/")
    for response in (listed, detail):
        assert not leaks(response.content.decode(), secret_box)
    assert (detail.json()["location"], detail.json()["location_masked"]) == (None, True)
    assert_problem(
        client.post(f"{VIALS_URL}{masked[0].public_id}/reveal-location/"),
        403,
        "location_grant_required",
    )
