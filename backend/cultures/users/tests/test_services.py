"""The user services: one event each, privilege changes with a reason, passwords without values."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from django.db import IntegrityError, transaction

from cultures.audit.context import AuditContext, MissingAuditContext, audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.audit.registry import EVENT_TYPES
from cultures.core.exceptions import RuleViolation
from cultures.users import services
from cultures.users.models import User

from .conftest import PASSWORD, make_user, trail

pytestmark = pytest.mark.django_db


def events(user: User) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(subject_id=user.public_id).order_by("pk"))


def test_user_create_records_the_new_user_without_a_password_value(
    audited: AuditContext, staff: User
) -> None:
    user = services.user_create(username="newbie", password=PASSWORD, email="New@Example.ORG")

    assert user.check_password(PASSWORD)
    assert (user.is_active, user.is_staff, user.is_superuser) == (True, False, False)
    (event,) = events(user)
    assert (event.event_type, event.actor, event.channel, event.request_id) == (
        "user_created",
        staff,
        Channel.COMMAND,
        "cmd-1",
    )
    assert (event.subject_type, event.lab_id) == ("user", None)
    # The fields that got a value, never the value itself (#37). Empty names: not listed.
    assert event.changes == {
        "username": "changed",
        "email": "changed",
        "has_usable_password": [None, True],
    }
    assert user.email == "New@example.org"  # the domain is normalized, as by Django


def test_user_create_without_a_password_gives_no_usable_one(audited: AuditContext) -> None:
    user = services.user_create(username="sso-only", password=None)
    assert not user.has_usable_password()
    assert events(user)[0].changes["has_usable_password"] == [None, False]


def test_a_taken_username_is_a_conflict_and_leaves_no_trace(
    audited: AuditContext, member: User
) -> None:
    before = (User.objects.count(), *trail())
    with pytest.raises(services.UsernameTaken) as refused:
        services.user_create(username="member", password=None)
    assert (refused.value.code, refused.value.attr) == ("username_taken", "username")
    assert (User.objects.count(), *trail()) == before


def test_user_update_records_only_the_fields_that_changed(
    audited: AuditContext, member: User
) -> None:
    services.user_update(
        user=member, changes={"first_name": "Augusta", "last_name": "Lovelace", "email": "a@b.org"}
    )

    (event,) = events(member)
    assert event.event_type == "user_changed"
    assert event.changes == {"first_name": "changed", "email": "changed"}  # no values (#37)
    member.refresh_from_db()
    assert (member.first_name, member.email) == ("Augusta", "a@b.org")


def test_user_update_without_a_change_records_nothing(audited: AuditContext, member: User) -> None:
    before = trail()
    services.user_update(user=member, changes={"first_name": "Ada"})
    assert trail() == before


@pytest.mark.parametrize("field", ["is_staff", "is_superuser", "is_active", "password"])
def test_user_update_refuses_privileges_and_the_password(
    field: str, audited: AuditContext, member: User
) -> None:
    with pytest.raises(ValueError, match="changes only"):
        services.user_update(user=member, changes={field: "x"})


def test_a_username_taken_by_an_update_is_a_conflict(
    audited: AuditContext, member: User, staff: User
) -> None:
    with pytest.raises(services.UsernameTaken):
        services.user_update(user=member, changes={"username": "staff"})
    member.refresh_from_db()
    assert member.username == "member"


@dataclass(frozen=True)
class Grant:
    service: Callable[..., User]
    field: str  # the flag, also the service's keyword
    code: str  # the event type


GRANTS = [
    Grant(services.user_set_staff, "is_staff", "user_staff_changed"),
    Grant(services.user_set_superuser, "is_superuser", "user_superuser_changed"),
]


@pytest.mark.parametrize("grant", GRANTS, ids=lambda g: g.field)
def test_a_privilege_grant_is_its_own_event_with_the_reason(
    grant: Grant, audited: AuditContext, member: User
) -> None:
    field, code = grant.field, grant.code
    grant.service(user=member, reason="runs the backups", **{field: True})

    member.refresh_from_db()
    assert getattr(member, field) is True
    (event,) = events(member)
    assert (event.event_type, event.reason, event.changes) == (
        code,
        "runs the backups",
        {field: [False, True]},
    )


@pytest.mark.parametrize("grant", GRANTS, ids=lambda g: g.field)
@pytest.mark.parametrize("reason", [None, "", "  "])
def test_a_privilege_grant_without_a_reason_is_refused_and_changes_nothing(
    reason: str | None, grant: Grant, audited: AuditContext, member: User
) -> None:
    before = trail()
    with pytest.raises(RuleViolation) as refused:
        grant.service(user=member, reason=reason, **{grant.field: True})
    assert (refused.value.code, refused.value.attr) == ("reason_required", "reason")
    member.refresh_from_db()
    assert getattr(member, grant.field) is False
    assert trail() == before


def test_a_grant_that_changes_nothing_records_nothing(audited: AuditContext, staff: User) -> None:
    before = trail()
    services.user_set_staff(user=staff, is_staff=True, reason="already staff")
    assert trail() == before


def test_user_activate_needs_a_reason(audited: AuditContext) -> None:
    gone = make_user("gone", is_active=False)
    with pytest.raises(RuleViolation):
        services.user_activate(user=gone)
    services.user_activate(user=gone, reason="back from leave")
    gone.refresh_from_db()
    assert gone.is_active
    assert [(e.event_type, e.reason) for e in events(gone)] == [
        ("user_activated", "back from leave")
    ]


@pytest.mark.parametrize("code", ["user_activated", "user_staff_changed", "user_superuser_changed"])
def test_the_database_refuses_a_privilege_event_without_a_reason(code: str, staff: User) -> None:
    """The check constraint, under the service's check: a direct insert is refused too."""
    assert EVENT_TYPES[code].reason_required
    event = AuditEvent(
        event_type=code,
        actor=staff,
        actor_label="staff",
        actor_kind=ActorKind.USER,
        channel=Channel.WEB,
        request_id="r",
        subject_type="user",
        subject_id=staff.public_id,
        reason=" ",
    )
    with (
        pytest.raises(IntegrityError, match="audit_auditevent_reason_required"),
        transaction.atomic(),
    ):
        event.save()


def test_user_set_password_records_the_change_but_never_a_value(
    audited: AuditContext, member: User
) -> None:
    saved = services.user_set_password(user=member, raw_password=PASSWORD)

    assert saved.check_password(PASSWORD)
    (event,) = events(member)
    assert (event.event_type, event.changes) == (
        "user_password_changed",
        {"has_usable_password": [True, True]},
    )
    (row,) = RowChange.objects.filter(row_pk=str(member.pk), op="UPDATE")
    assert (row.new, row.txid, row.request_id) == (
        {"password": "redacted"},
        event.txid,
        event.request_id,
    )
    assert saved.password not in str(event.changes) + str(row.old) + str(row.new)


def test_user_set_password_none_removes_the_usable_password(
    audited: AuditContext, member: User
) -> None:
    services.user_set_password(user=member, raw_password=None)
    member.refresh_from_db()
    assert not member.has_usable_password()
    assert events(member)[0].changes == {"has_usable_password": [True, False]}


def test_superuser_create_records_the_user_and_both_grants_in_one_transaction() -> None:
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:x"
    ):
        root = services.superuser_create(username="root", password=PASSWORD, reason="first admin")

    assert (root.is_staff, root.is_superuser, root.check_password(PASSWORD)) == (True, True, True)
    recorded = events(root)
    assert [(e.event_type, e.reason) for e in recorded] == [
        ("user_created", ""),
        ("user_staff_changed", "first admin"),
        ("user_superuser_changed", "first admin"),
    ]
    assert len({e.txid for e in recorded}) == 1


def test_superuser_create_without_a_reason_creates_no_one(audited: AuditContext) -> None:
    before = (User.objects.count(), *trail())
    with pytest.raises(RuleViolation):
        services.superuser_create(username="root", password=PASSWORD)
    assert (User.objects.count(), *trail()) == before


def test_the_manager_creates_superusers_only_in_an_audit_context() -> None:
    with pytest.raises(MissingAuditContext):
        User.objects.create_superuser("root", password=PASSWORD)
    assert not User.objects.filter(username="root").exists()


def test_the_manager_creates_superusers_through_the_services() -> None:
    with audit_context(
        channel=Channel.COMMAND,
        actor_kind=ActorKind.SYSTEM,
        actor_label="command:x",
        reason="first admin",
    ):
        root = User.objects.create_superuser("root", "root@example.org", PASSWORD)
    assert [e.event_type for e in events(root)] == [
        "user_created",
        "user_staff_changed",
        "user_superuser_changed",
    ]


def test_the_manager_refuses_fields_it_would_not_record() -> None:
    with pytest.raises(ValueError, match="no other fields"):
        User.objects.create_superuser("root", password=PASSWORD, is_staff=False)
