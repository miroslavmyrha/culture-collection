"""The VRAT access list (act 281/2002 Sb., § 14a(4), ADR 0009 amendment of 2026-11-03): a manager
puts an active member of the lab on the list of the people with access to its highly risky agents
and takes them off it, each with a reason and an event. Leaving the lab, a deactivation and an
erasure end the entry in the same transaction. The table holds the history on its own: one open
entry per person and lab, ended once, never deleted, and the runtime role has no DELETE."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import pytest
import time_machine
from django.db import DatabaseError, IntegrityError, InternalError, connection, transaction
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.audit.tests.conftest import refused as refused_sql
from cultures.core.exceptions import DomainError, Forbidden, NotFound, RuleViolation
from cultures.core.testing import QueryBaseline, ViewsetContract, assert_problem, logged_in
from cultures.labs import selectors, services
from cultures.labs.access import access_for
from cultures.labs.api.views import VratAccessViewSet
from cultures.labs.models import Lab, Membership, VratAccess
from cultures.labs.permissions import Role
from cultures.users import services as users
from cultures.users.models import User

from .conftest import LAB_URL, make_user, member_of, membership

pytestmark = pytest.mark.django_db
VRAT_URL = f"{LAB_URL}vrat-access/"
REASON = "works with the VRAT strains"


def snapshot() -> tuple[Any, ...]:
    return (
        list(VratAccess.objects.order_by("pk").values()),
        AuditEvent.objects.count(),
        RowChange.objects.count(),
    )


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> None:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before


def grant(manager: User, lab: Lab, user: User, reason: str = REASON) -> VratAccess:
    return services.vrat_access_grant(access=access_for(manager), lab=lab, user=user, reason=reason)


def end(manager: User, entry: VratAccess, reason: str = "moved to another project") -> None:
    services.vrat_access_end(access=access_for(manager), entry=entry, reason=reason)


def last_events(n: int) -> list[str]:
    return list(AuditEvent.objects.order_by("-pk").values_list("event_type", flat=True)[:n])


# Services.


@pytest.mark.rule("R-ACCESS-01")
def test_a_manager_puts_a_member_on_the_list_and_takes_them_off_with_reasons_and_events(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    entry = grant(manager, lab, viewer, "  works with the VRAT strains ")
    assert (entry.user, entry.granted_by, entry.reason, entry.ended_at) == (
        viewer,
        manager,
        REASON,
        None,
    )
    event = AuditEvent.objects.order_by("-pk").first()
    assert event is not None
    assert (event.event_type, event.actor, event.lab_id, event.reason, event.subject_id) == (
        "vrat_access_granted",
        manager,
        lab.pk,
        REASON,
        entry.public_id,
    )
    assert event.changes == {"user": [None, str(viewer.public_id)]}
    end(manager, entry, "moved on")
    entry.refresh_from_db()
    assert (entry.ended_by, entry.end_reason) == (manager, "moved on")
    assert entry.ended_at is not None
    last = AuditEvent.objects.order_by("-pk").first()
    assert last is not None
    assert (last.event_type, last.reason, last.subject_id) == (
        "vrat_access_ended",
        "moved on",
        entry.public_id,
    )
    assert last.changes == {"user": [str(viewer.public_id)] * 2, "ended": [False, True]}
    # Back on the list later: a new row, the old one stays as it ended.
    grant(manager, lab, viewer)
    assert VratAccess.objects.filter(user=viewer).count() == 2


def test_the_events_hold_no_personal_value(
    as_manager: AuditContext, manager: User, lab: Lab
) -> None:
    person = member_of(lab, Role.VIEWER, "jana.novakova", first_name="Jana", last_name="Nováková")
    person.email = "jana@example.org"
    person.save()
    end(manager, grant(manager, lab, person))
    users.user_deactivate(user=person, reason="left the institute")
    values = [
        repr((e.changes, e.reason, e.actor_label))
        for e in AuditEvent.objects.filter(event_type__startswith="vrat_access")
    ]
    assert len(values) == 2
    for text in values:
        for personal in ("jana.novakova", "Jana", "Nováková", "jana@example.org"):
            assert personal not in text


def test_a_manager_may_be_on_it_too(as_manager: AuditContext, manager: User, lab: Lab) -> None:
    grant(manager, lab, manager)
    assert VratAccess.objects.filter(user=manager, ended_at__isnull=True).count() == 1


def test_a_second_open_entry_is_refused(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    grant(manager, lab, viewer)
    refused(
        services.AlreadyOnList, "already_on_list", lambda: grant(manager, lab, viewer), "username"
    )


@pytest.mark.rule("R-ACCESS-01")
@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_a_manager_puts_on_and_takes_off(
    as_manager: AuditContext, team: dict[Role, User], lab: Lab, viewer: User, role: Role
) -> None:
    refused(Forbidden, "permission_denied", lambda: grant(team[role], lab, viewer))
    entry = grant(team[Role.MANAGER], lab, viewer)
    refused(Forbidden, "permission_denied", lambda: end(team[role], entry))


def test_a_manager_demoted_since_the_request_began_is_refused(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    access = access_for(manager)
    member_of(lab, Role.MANAGER, "second")
    Membership.objects.filter(user=manager, lab=lab).update(role=Role.CURATOR)
    refused(
        Forbidden,
        "permission_denied",
        lambda: services.vrat_access_grant(access=access, lab=lab, user=viewer, reason=REASON),
    )


@pytest.mark.rule("R-ACCESS-01")
def test_a_reason_is_required_both_ways(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    refused(RuleViolation, "reason_required", lambda: grant(manager, lab, viewer, " "), "reason")
    entry = grant(manager, lab, viewer)
    refused(RuleViolation, "reason_required", lambda: end(manager, entry, "\n"), "reason")


@pytest.mark.rule("R-ACCESS-01")
def test_an_entry_ends_once(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    entry = grant(manager, lab, viewer)
    end(manager, entry)
    refused(services.VratAccessEnded, "vrat_access_ended", lambda: end(manager, entry))


@pytest.mark.rule("R-ACCESS-02")
def test_only_an_active_member_goes_on_the_list(
    as_manager: AuditContext, manager: User, lab: Lab, outsider: User, stranger: User
) -> None:
    # In another lab only, and in no lab: the same field error as an unknown user.
    for user in (outsider, stranger):
        refused(services.NotAMember, "invalid_user", partial(grant, manager, lab, user), "username")
    inactive = member_of(lab, Role.VIEWER, "inactive", is_active=False)
    refused(services.UnknownUser, "invalid_user", lambda: grant(manager, lab, inactive), "username")


@pytest.mark.rule("R-ACCESS-02")
def test_removing_the_member_ends_the_entry_in_the_same_transaction(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    entry = grant(manager, lab, viewer)
    services.member_remove(access=access_for(manager), membership=membership(viewer, lab))
    entry.refresh_from_db()
    assert (entry.end_reason, entry.ended_by) == ("The member left the lab.", manager)
    assert last_events(2) == ["member_removed", "vrat_access_ended"]


def test_a_refused_removal_ends_nothing(as_manager: AuditContext, manager: User, lab: Lab) -> None:
    entry = grant(manager, lab, manager)
    refused(
        services.LastManager,
        "last_manager",
        lambda: services.membership_delete(membership=membership(manager, lab)),
    )
    entry.refresh_from_db()
    assert entry.ended_at is None


@pytest.mark.rule("R-ACCESS-02")
def test_deactivating_the_user_ends_every_entry_in_the_same_transaction(
    as_manager: AuditContext, manager: User, lab: Lab, other_lab: Lab, outsider: User
) -> None:
    person = member_of(lab, Role.TECHNICIAN, "person")
    Membership.objects.create(user=person, lab=other_lab, role=Role.VIEWER)
    here = grant(manager, lab, person)
    there = grant(outsider, other_lab, person)
    users.user_deactivate(user=person, reason="left the institute")
    for entry in (here, there):
        entry.refresh_from_db()
        assert (entry.end_reason, entry.ended_by) == ("The account was deactivated.", manager)
    assert last_events(3) == ["user_deactivated", "vrat_access_ended", "vrat_access_ended"]
    # Active again, the person is not back on the list: a manager puts them on anew.
    users.user_activate(user=person, reason="back")
    assert not VratAccess.objects.filter(user=person, ended_at__isnull=True).exists()


@pytest.mark.rule("R-ACCESS-02")
def test_deactivating_many_users_ends_their_entries(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User, curator: User
) -> None:
    entries = [grant(manager, lab, viewer), grant(manager, lab, curator)]
    users.users_deactivate(users=[viewer, curator], reason="the project ended")
    for entry in entries:
        entry.refresh_from_db()
        assert entry.end_reason == "The account was deactivated."


def test_a_refused_deactivation_ends_nothing(
    as_manager: AuditContext, manager: User, lab: Lab
) -> None:
    entry = grant(manager, lab, manager)
    refused(
        services.LastManager,
        "last_manager",
        lambda: users.user_deactivate(user=manager, reason="no"),
    )
    entry.refresh_from_db()
    assert entry.ended_at is None


@pytest.mark.rule("R-ACCESS-02")
def test_erasing_the_user_ends_the_entry_and_keeps_it_under_the_tombstone(
    manager: User, lab: Lab, viewer: User
) -> None:
    with audit_context(channel=Channel.API, actor=manager):
        entry = grant(manager, lab, viewer)
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:test"
    ):
        users.user_erase(user=viewer, reason="the person asked")
    entry.refresh_from_db()
    assert (entry.end_reason, entry.ended_by) == ("The account was erased.", None)
    assert last_events(3) == ["user_erased", "member_removed", "vrat_access_ended"]
    rows = logged_in(manager).get(VRAT_URL).json()
    assert [(r["username"], r["first_name"], r["last_name"], r["ended_by"]) for r in rows] == [
        (f"erased-{viewer.public_id}", "", "", None)
    ]


# The selector #160 asks: was this person on the list at that moment?


@pytest.mark.rule("R-ACCESS-01")
def test_has_vrat_access_answers_for_a_moment_before_during_and_after(
    manager: User, lab: Lab, viewer: User
) -> None:
    start = datetime(2026, 5, 4, 9, tzinfo=UTC)
    stop = start + timedelta(days=30)
    with time_machine.travel(start, tick=False), audit_context(channel=Channel.API, actor=manager):
        entry = grant(manager, lab, viewer)
    with time_machine.travel(stop, tick=False), audit_context(channel=Channel.API, actor=manager):
        end(manager, entry)

    def held(at: datetime) -> bool:
        return selectors.has_vrat_access(user=viewer, lab=lab, at=at)

    second = timedelta(seconds=1)
    assert [held(start - second), held(start), held(start + timedelta(days=3))] == [
        False,
        True,
        True,
    ]
    # ended_at is the first moment without access.
    assert [held(stop - second), held(stop), held(stop + second)] == [True, False, False]
    # Another lab, another person: no.
    assert selectors.has_vrat_access(user=manager, lab=lab, at=start + second) is False
    other = make_user("elsewhere")
    assert selectors.has_vrat_access(user=other, lab=lab, at=start + second) is False


def test_has_vrat_access_holds_for_an_open_entry_and_ends_with_the_membership(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User, other_lab: Lab
) -> None:
    grant(manager, lab, viewer)
    later = datetime.now(UTC) + timedelta(days=1)
    assert selectors.has_vrat_access(user=viewer, lab=lab, at=later) is True
    assert selectors.has_vrat_access(user=viewer, lab=other_lab, at=later) is False
    services.member_remove(access=access_for(manager), membership=membership(viewer, lab))
    assert selectors.has_vrat_access(user=viewer, lab=lab, at=later) is False


# The table on its own.


@pytest.mark.rule("R-ACCESS-01")
def test_one_open_entry_per_person_and_lab(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    grant(manager, lab, viewer)
    with pytest.raises(IntegrityError, match="labs_vrataccess_one_open"), transaction.atomic():
        VratAccess.objects.create(lab=lab, user=viewer, granted_by=manager, reason="again")


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"reason": " "}, "labs_vrataccess_reason_given"),
        ({"end_reason": "why"}, "labs_vrataccess_end_complete"),
    ],
)
def test_the_database_refuses_a_bad_entry(
    manager: User, lab: Lab, viewer: User, fields: dict[str, Any], constraint: str
) -> None:
    values = {"lab": lab, "user": viewer, "granted_by": manager, "reason": "r", **fields}
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        VratAccess.objects.create(**values)


def test_the_database_refuses_an_end_before_the_start(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    entry = grant(manager, lab, viewer)
    with (
        pytest.raises(IntegrityError, match="labs_vrataccess_ends_after_start"),
        transaction.atomic(),
    ):
        VratAccess.objects.filter(pk=entry.pk).update(
            ended_at=entry.created_at - timedelta(seconds=1), end_reason="early"
        )


@pytest.mark.rule("R-ACCESS-02")
@pytest.mark.parametrize("who", ["outsider", "stranger", "inactive"])
def test_the_database_puts_only_an_active_member_on_the_list(
    manager: User, lab: Lab, who: str, request: pytest.FixtureRequest
) -> None:
    if who == "inactive":
        user = member_of(lab, Role.VIEWER, "inactive", is_active=False)
    else:  # a manager of another lab only, and a user in no lab
        user = request.getfixturevalue(who)
    with (
        pytest.raises(IntegrityError, match="starts open, for an active member"),
        transaction.atomic(),
    ):
        VratAccess.objects.create(lab=lab, user=user, granted_by=manager, reason="past it")


def test_the_database_writes_no_entry_ended_already(manager: User, lab: Lab, viewer: User) -> None:
    with pytest.raises(IntegrityError, match="starts open"), transaction.atomic():
        VratAccess.objects.create(
            lab=lab,
            user=viewer,
            granted_by=manager,
            reason="r",
            ended_at=datetime.now(UTC),
            end_reason="already over",
        )


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("UPDATE labs_vrataccess SET reason = 'other'", "changes only once"),
        ("UPDATE labs_vrataccess SET user_id = granted_by_id", "changes only once"),
        (
            "UPDATE labs_vrataccess SET created_at = created_at - interval '1 day'",
            "changes only once",
        ),
        ("DELETE FROM labs_vrataccess", "never deleted"),
    ],
)
@pytest.mark.rule("R-ACCESS-01")
def test_an_entry_changes_only_when_it_ends_and_is_never_deleted(
    *, as_manager: AuditContext, manager: User, lab: Lab, viewer: User, statement: str, message: str
) -> None:
    grant(manager, lab, viewer)
    with (
        pytest.raises((IntegrityError, InternalError), match=message),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement)


@pytest.mark.rule("R-ACCESS-01")
def test_an_ended_entry_is_never_reopened(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    end(manager, grant(manager, lab, viewer))
    with (
        pytest.raises((IntegrityError, InternalError), match="changes only once"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE labs_vrataccess SET ended_at = NULL, ended_by_id = NULL, end_reason = ''"
        )


def _at_commit(cursor: CursorWrapper, statement: str, params: list[Any]) -> None:
    """Run the statement and the deferred checks as a commit would."""
    with transaction.atomic():
        cursor.execute(statement, params)
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.rule("R-ACCESS-02")
def test_a_deactivation_past_the_service_with_an_open_entry_fails_at_commit(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User
) -> None:
    grant(manager, lab, viewer)
    with (
        connection.cursor() as cursor,
        pytest.raises(DatabaseError, match="an inactive account holds no open VRAT access entry"),
    ):
        _at_commit(cursor, "UPDATE users_user SET is_active = false WHERE id = %s", [viewer.pk])
    # Without an open entry the same write passes.
    with connection.cursor() as cursor:
        _at_commit(cursor, "UPDATE users_user SET is_active = false WHERE id = %s", [manager.pk])


@pytest.mark.rule("R-ACCESS-02")
def test_a_membership_deleted_past_the_service_with_an_open_entry_fails_at_commit(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User, curator: User
) -> None:
    grant(manager, lab, viewer)
    delete = "DELETE FROM labs_membership WHERE user_id = %s AND lab_id = %s"
    with (
        connection.cursor() as cursor,
        pytest.raises(DatabaseError, match="who left the lab holds no open VRAT access entry"),
    ):
        _at_commit(cursor, delete, [viewer.pk, lab.pk])
    with connection.cursor() as cursor:
        _at_commit(cursor, delete, [curator.pk, lab.pk])


@pytest.mark.rule("R-ACCESS-01")
def test_the_runtime_role_puts_on_and_ends_but_deletes_nothing(
    as_manager: AuditContext, manager: User, lab: Lab, viewer: User, runtime_role: CursorWrapper
) -> None:
    entry = grant(manager, lab, viewer)
    end(manager, entry)
    refused_sql(runtime_role, "DELETE FROM labs_vrataccess", "permission denied")
    refused_sql(
        runtime_role,
        "UPDATE labs_vrataccess SET ended_at = NULL, ended_by_id = NULL, end_reason = ''",
        "changes only once",
    )


# The API.


@pytest.mark.rule("R-ACCESS-01")
@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
def test_only_managers_see_and_change_the_list(
    *,
    role: Role,
    team: dict[Role, User],
    manager: User,
    lab: Lab,
    viewer: User,
    as_manager: AuditContext,
) -> None:
    entry = grant(manager, lab, viewer)
    client = logged_in(team[role])
    before = snapshot()
    assert_problem(client.get(VRAT_URL), 403, "permission_denied")
    assert_problem(client.get(f"{VRAT_URL}{entry.public_id}/"), 404, "not_found")
    body = {"username": "x", "reason": ""}  # invalid on purpose: 403 comes before the input
    assert_problem(
        client.post(VRAT_URL, body, content_type="application/json"), 403, "permission_denied"
    )
    ending = f"{VRAT_URL}{entry.public_id}/end/"
    assert_problem(client.post(ending, {}, content_type="application/json"), 404, "not_found")
    assert snapshot() == before


def test_outsiders_and_anonymous_get_404_and_401(
    outsider: User, manager: User, lab: Lab, viewer: User, as_manager: AuditContext
) -> None:
    entry = grant(manager, lab, viewer)
    for url in (VRAT_URL, f"{VRAT_URL}{entry.public_id}/"):
        assert_problem(logged_in(outsider).get(url), 404, "not_found")
        assert_problem(logged_in(None).get(url), 401, "not_authenticated")
    response = logged_in(outsider).post(VRAT_URL, {}, content_type="application/json")
    assert_problem(response, 404, "not_found")


def test_a_manager_puts_on_lists_and_ends_through_the_api(
    manager: User, lab: Lab, curator: User
) -> None:
    curator.first_name, curator.last_name = "Cora", "Curie"
    curator.save()
    client = logged_in(manager)
    created = client.post(
        VRAT_URL, {"username": "curator", "reason": REASON}, content_type="application/json"
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert {
        k: body[k] for k in ("username", "first_name", "last_name", "granted_by", "reason")
    } == {
        "username": "curator",
        "first_name": "Cora",
        "last_name": "Curie",
        "granted_by": "manager",
        "reason": REASON,
    }
    assert (body["ended_at"], body["ended_by"], body["end_reason"]) == (None, None, "")
    again = client.post(
        VRAT_URL, {"username": "curator", "reason": "twice"}, content_type="application/json"
    )
    assert_problem(again, 400, "already_on_list", "username")
    ended = client.post(
        f"{VRAT_URL}{body['public_id']}/end/",
        {"reason": "moved on"},
        content_type="application/json",
    )
    assert ended.status_code == 204
    assert_problem(
        client.post(
            f"{VRAT_URL}{body['public_id']}/end/",
            {"reason": "again"},
            content_type="application/json",
        ),
        409,
        "vrat_access_ended",
    )
    client.post(
        VRAT_URL, {"username": "manager", "reason": REASON}, content_type="application/json"
    )
    client.post(
        VRAT_URL, {"username": "curator", "reason": "back"}, content_type="application/json"
    )
    listed = client.get(VRAT_URL).json()
    # Open entries by username, then the ended ones: the history stays in the list.
    assert [(r["username"], r["ended_at"] is None, r["end_reason"]) for r in listed] == [
        ("curator", True, ""),
        ("manager", True, ""),
        ("curator", False, "moved on"),
    ]
    assert listed[2]["ended_by"] == "manager"
    # An ended entry is still found: it is part of the history.
    detail = client.get(f"{VRAT_URL}{body['public_id']}/")
    assert detail.status_code == 200
    assert detail.json()["end_reason"] == "moved on"


@pytest.mark.parametrize(
    ("username", "code"),
    [("nobody", "invalid"), ("inactive", "invalid"), ("outsider", "invalid_user")],
)
def test_the_api_gives_a_field_error_for_who_cannot_be_on_the_list(
    manager: User, lab: Lab, outsider: User, username: str, code: str
) -> None:
    """Unknown and inactive users fail in the input (does_not_exist), an active user of another
    lab in the service (invalid_user); both on the username field."""
    member_of(lab, Role.VIEWER, "inactive", is_active=False)
    before = snapshot()
    response = logged_in(manager).post(
        VRAT_URL, {"username": username, "reason": REASON}, content_type="application/json"
    )
    body = assert_problem(response, 400, code, "username")
    assert [e["code"] for e in body["errors"]] == [
        "does_not_exist" if code == "invalid" else "invalid_user"
    ]
    assert snapshot() == before


def test_a_reason_is_required_through_the_api(manager: User, lab: Lab, viewer: User) -> None:
    response = logged_in(manager).post(
        VRAT_URL, {"username": "viewer", "reason": "  "}, content_type="application/json"
    )
    assert_problem(response, 400, "invalid", "reason")  # blank once trimmed, in the input
    assert not VratAccess.objects.exists()


def test_the_list_query_count_is_exact_and_flat(
    manager: User, lab: Lab, query_baseline: QueryBaseline
) -> None:
    with audit_context(channel=Channel.API, actor=manager):
        for i in range(12):
            person = member_of(lab, Role.TECHNICIAN, f"person-{i:02}")
            entry = grant(manager, lab, person)
            if i % 2:
                end(manager, entry)
    client = logged_in(manager)
    # Session, user, memberships, the lab, the entries with the three users joined.
    with query_baseline("vrat_access_list") as captured:
        response = client.get(VRAT_URL)
    assert len(response.json()) == 12
    scoped = [q["sql"] for q in captured.captured_queries if 'FROM "labs_vrataccess"' in q["sql"]]
    assert len(scoped) == 1
    assert '"labs_vrataccess"."lab_id" IN (' in scoped[0]


class TestVratAccessContract(ViewsetContract):
    """Only managers read and write the list, so no role reads without writing: the refused
    writes per role are in test_only_managers_see_and_change_the_list above."""

    viewset = VratAccessViewSet
    url = VRAT_URL
    writes = ()

    @pytest.fixture
    def obj(self, manager: User, lab: Lab, viewer: User, as_manager: AuditContext) -> VratAccess:
        return grant(manager, lab, viewer)

    @pytest.fixture
    def reader(self, manager: User) -> User:
        return manager

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager

    # Not paged, and nested under a lab the outsider is not a member of: a 404 for all of it.
    def test_list_is_scoped(self, obj: VratAccess, reader: User, outsider: User) -> None:
        listed = logged_in(reader).get(self.url).json()
        assert str(obj.public_id) in [row["public_id"] for row in listed]
        assert_problem(logged_in(outsider).get(self.url), 404, "not_found")


def test_no_entry_is_found_from_the_wrong_lab(
    manager: User, lab: Lab, viewer: User, as_manager: AuditContext
) -> None:
    entry = grant(manager, lab, viewer)
    with pytest.raises(NotFound):
        services.vrat_access_end(
            access=access_for(manager),
            entry=VratAccess(pk=entry.pk + 1000, lab_id=lab.pk),
            reason="r",
        )
