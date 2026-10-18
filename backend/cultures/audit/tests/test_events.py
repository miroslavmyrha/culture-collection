"""Service events: same transaction as the change, fail closed, nested contexts, batches."""

import uuid
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from model_bakery import baker

from cultures.audit import context as audit
from cultures.audit.context import AuditContext, MissingAuditContext, audit_context
from cultures.audit.events import Change, record_event
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.audit.registry import USER_DEACTIVATED, EventType, register
from cultures.core.exceptions import RuleViolation
from cultures.users.models import User
from cultures.users.services import user_deactivate, users_deactivate

from .conftest import make_user

pytestmark = pytest.mark.django_db


def test_a_service_writes_one_event_with_every_field(
    admin: User, member: User, audited: AuditContext
) -> None:
    user_deactivate(user=member)

    event = AuditEvent.objects.get()
    assert (event.event_type, event.subject_type, event.subject_id) == (
        "user_deactivated",
        "user",
        member.public_id,
    )
    assert (event.actor, event.actor_label, event.actor_kind) == (admin, "admin", "user")
    assert (event.channel, event.request_id, event.reason) == ("command", "cmd-1", "left the lab")
    assert (event.changes, event.batch_id, event.schema_version) == (
        {"is_active": [True, False]},
        None,
        1,
    )


def test_a_rollback_leaves_neither_the_change_nor_the_event(
    member: User, audited: AuditContext
) -> None:
    class Boom(Exception):
        pass

    with pytest.raises(Boom), transaction.atomic():
        user_deactivate(user=member)
        raise Boom

    member.refresh_from_db()
    assert member.is_active is True
    assert not AuditEvent.objects.exists()


def test_a_write_outside_any_context_raises_and_changes_nothing(member: User) -> None:
    with pytest.raises(MissingAuditContext):
        user_deactivate(user=member, reason="left the lab")
    member.refresh_from_db()
    assert member.is_active is True
    assert not AuditEvent.objects.exists()


def test_record_event_outside_any_context_raises(member: User) -> None:
    change = Change("user", member.public_id, {})
    with pytest.raises(MissingAuditContext):
        record_event(USER_DEACTIVATED, change, reason="x")


def test_nested_contexts_restore_the_outer_one(admin: User) -> None:
    with audit_context(channel=Channel.COMMAND, actor=admin) as outer:
        with audit_context(
            channel=Channel.TASK, actor_kind=ActorKind.SYSTEM, request_id="inner"
        ) as inner:
            assert audit.current_context() == inner
        assert audit.current_context() == outer
    with pytest.raises(MissingAuditContext):
        audit.current_context()


def test_an_inner_context_that_raises_still_restores_the_outer_one(admin: User) -> None:
    with audit_context(channel=Channel.COMMAND, actor=admin) as outer:
        with pytest.raises(ZeroDivisionError), audit_context(channel=Channel.TASK):
            _ = 1 / 0
        assert audit.current_context() == outer


def test_a_user_actor_kind_without_an_actor_is_refused(member: User) -> None:
    with audit_context(channel=Channel.COMMAND), pytest.raises(MissingAuditContext):
        user_deactivate(user=member, reason="left the lab")
    assert not AuditEvent.objects.exists()


def test_a_system_actor_is_recorded_by_its_label(member: User) -> None:
    with audit_context(
        channel=Channel.COMMAND,
        actor_kind=ActorKind.SYSTEM,
        actor_label="command:expire_accounts",
        reason="expired",
    ):
        user_deactivate(user=member)
    event = AuditEvent.objects.get()
    assert (event.actor, event.actor_kind, event.actor_label) == (
        None,
        "system",
        "command:expire_accounts",
    )


@pytest.mark.parametrize("reason", ["", "  "])
def test_a_type_that_needs_a_reason_refuses_a_blank_one(
    admin: User, member: User, reason: str
) -> None:
    with audit_context(channel=Channel.COMMAND, actor=admin), pytest.raises(RuleViolation) as error:
        user_deactivate(user=member, reason=reason)
    assert (error.value.code, error.value.attr) == ("reason_required", "reason")
    member.refresh_from_db()
    assert member.is_active is True
    assert not AuditEvent.objects.exists()


def test_an_explicit_reason_overrides_the_contexts(member: User, audited: AuditContext) -> None:
    user_deactivate(user=member, reason="asked to leave")
    assert AuditEvent.objects.get().reason == "asked to leave"


def event_row(**overrides: object) -> AuditEvent:
    """An event built past the Python checks, so only the database can refuse it."""
    values: dict[str, object] = {
        "event_type": "user_deactivated",
        "actor": None,
        "actor_kind": "system",
        "actor_label": "x",
        "channel": "command",
        "request_id": "r",
        "reason": "because",
        "subject_type": "user",
        "subject_id": uuid.uuid4(),
        **overrides,
    }
    return AuditEvent(**values)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"reason": " "}, "audit_auditevent_reason_required"),
        ({"actor_kind": "user"}, "audit_auditevent_user_needs_actor"),
        ({"actor_kind": "robot"}, "audit_auditevent_actor_kind_valid"),
        ({"channel": "email"}, "audit_auditevent_channel_valid"),
    ],
)
def test_the_database_refuses_an_invalid_event(
    overrides: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint), transaction.atomic():
        event_row(**overrides).save()


def test_the_database_accepts_the_valid_event_those_cases_start_from() -> None:
    event_row().save()
    assert AuditEvent.objects.count() == 1


def test_event_types_are_registered_once() -> None:
    with pytest.raises(ValueError, match="registered twice"):
        register(EventType("user_deactivated", "duplicate"))


def test_an_unregistered_event_type_is_refused(member: User, audited: AuditContext) -> None:
    stray = EventType("user_renamed", "{actor} renamed {subject}")
    with pytest.raises(ValueError, match="unregistered"):
        record_event(stray, Change("user", member.public_id, {}))


def test_one_transaction_shares_one_occurred_at(audited: AuditContext) -> None:
    first, second = make_user("a"), make_user("b")
    with transaction.atomic():
        user_deactivate(user=first)
        user_deactivate(user=second)
    assert AuditEvent.objects.values_list("occurred_at", flat=True).distinct().count() == 1


def test_an_actor_with_events_cannot_be_deleted(
    admin: User, member: User, audited: AuditContext
) -> None:
    user_deactivate(user=member)
    with pytest.raises(ProtectedError):
        admin.delete()  # deactivate users, never delete them


def test_a_batch_writes_one_event_per_object_plus_a_batch_event(
    admin: User, audited: AuditContext
) -> None:
    members = baker.make(User, _quantity=3)

    count = users_deactivate(users=members)

    assert count == 3
    assert not User.objects.filter(pk__in=[m.pk for m in members], is_active=True).exists()
    events = list(AuditEvent.objects.order_by("pk"))
    assert [e.event_type for e in events] == [
        "user_deactivated",
        "user_deactivated",
        "user_deactivated",
        "users_deactivated",
    ]
    assert [e.subject_id for e in events[:3]] == [m.public_id for m in members]
    batch = events[3]
    assert (batch.subject_type, batch.subject_id, batch.changes) == (
        "batch",
        batch.batch_id,
        {"count": [None, 3]},
    )
    assert {(e.batch_id, e.occurred_at, e.request_id) for e in events} == {
        (batch.batch_id, batch.occurred_at, "cmd-1")
    }
    assert batch.batch_id is not None
    assert {(e.actor, e.reason) for e in events} == {(admin, "left the lab")}


def test_a_batch_skips_users_that_are_already_inactive(audited: AuditContext) -> None:
    active, inactive = make_user("active"), baker.make(User, is_active=False)
    assert users_deactivate(users=[active, inactive]) == 1
    assert list(
        AuditEvent.objects.filter(event_type="user_deactivated").values_list(
            "subject_id", flat=True
        )
    ) == [active.public_id]


# savepoint, read and set the trigger settings, lock, read their labs (none here: the lab
# check has its own tests), update, one INSERT for every event, restore the settings,
# release the savepoint
BATCH_QUERIES = 9


@pytest.mark.parametrize("count", [2, 6])
def test_a_batch_writes_all_its_events_in_one_insert(
    audited: AuditContext, count: int, django_assert_num_queries: Any
) -> None:
    """The same queries for 2 and for 6 users: bulk_create, not one INSERT per event."""
    members = baker.make(User, _quantity=count)
    with django_assert_num_queries(BATCH_QUERIES):
        users_deactivate(users=members)
    assert AuditEvent.objects.count() == count + 1
