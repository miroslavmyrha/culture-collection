"""No personal value enters a service event (#37, ADR 0005 update of 2026-10-18).

Every public service of cultures.users.services runs here with a marker string
in every personal value it touches, and with a marked user as the actor. The
marker must then appear in no column of audit_auditevent: not in `changes`,
not in `actor_label`. A new service fails the walk until it has a scenario.
"""

from collections.abc import Callable

import pytest
from django.db import connection

from cultures.audit.context import audit_context, audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.models import AuditEvent, Channel
from cultures.audit.registry import PERSONAL_CHANGED, PERSONAL_FIELDS, USER_CHANGED
from cultures.labs.tests.test_lock_invariant import public_services
from cultures.users import services
from cultures.users.models import User

from .conftest import make_user

pytestmark = pytest.mark.django_db

MARK = "zzmark7q"
REASON = "a scheduled account review"  # names nobody


def marked_user(tag: str) -> User:
    with audit_context(channel=Channel.COMMAND, actor=make_user(f"op-{tag}")):
        return services.user_create(
            username=f"{MARK}-{tag}",
            password=None,
            email=f"{MARK}.{tag}@example.org",
            first_name=f"{MARK} first",
            last_name=f"{MARK} last",
        )


def update_twice(user: User) -> None:
    for n in (1, 2):
        services.user_update(
            user=user,
            changes={
                "username": f"{MARK}-renamed-{n}",
                "first_name": f"{MARK} first {n}",
                "last_name": f"{MARK} last {n}",
                "email": f"{MARK}.{n}@example.org",
            },
        )


SCENARIOS: dict[str, Callable[[User, User], object]] = {
    # (actor, subject): the actor is marked too, so a label with its name would be found.
    "user_create": lambda actor, subject: marked_user("new"),
    "user_update": lambda actor, subject: update_twice(subject),
    "user_activate": lambda actor, subject: (
        services.user_deactivate(user=subject, reason=REASON),
        services.user_activate(user=subject, reason=REASON),
    ),
    "user_deactivate": lambda actor, subject: services.user_deactivate(user=subject, reason=REASON),
    "users_deactivate": lambda actor, subject: services.users_deactivate(
        users=[subject], reason=REASON
    ),
    "user_set_staff": lambda actor, subject: services.user_set_staff(
        user=subject, is_staff=True, reason=REASON
    ),
    "user_set_superuser": lambda actor, subject: services.user_set_superuser(
        user=subject, is_superuser=True, reason=REASON
    ),
    "user_set_password": lambda actor, subject: services.user_set_password(
        user=subject, raw_password=f"{MARK}-password-value"
    ),
    "user_login_limits_clear": lambda actor, subject: services.user_login_limits_clear(
        user=subject, reason=REASON
    ),
    "user_erase": lambda actor, subject: services.user_erase(user=subject, reason=REASON),
    "superuser_create": lambda actor, subject: services.superuser_create(
        username=f"{MARK}-root", password=f"{MARK}-pw", email=f"{MARK}@example.org", reason=REASON
    ),
}


def events_holding(text: str) -> list[str]:
    """Every event whose row, cast to text (all columns), contains `text`."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT e.event_type FROM audit_auditevent e WHERE strpos(e::text, %s) > 0", [text]
        )
        return [event_type for (event_type,) in cursor.fetchall()]


def test_every_user_service_has_a_scenario() -> None:
    found = public_services(services)
    assert len(found) > 5
    assert sorted(found ^ set(SCENARIOS)) == []


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_a_user_service_leaves_no_personal_value_in_any_event(name: str) -> None:
    actor, subject = marked_user("actor"), marked_user("subject")
    before = AuditEvent.objects.count()
    with audit_context(channel=Channel.COMMAND, actor=actor, reason=REASON):
        SCENARIOS[name](actor, subject)

    assert AuditEvent.objects.count() > before  # the scenario recorded something to search
    assert events_holding(MARK) == []
    assert events_holding("@example.org") == []


def test_the_profile_fields_are_the_personal_fields_of_a_user() -> None:
    assert set(services.PROFILE_FIELDS) <= set(PERSONAL_FIELDS["user"])


def test_record_event_drops_a_personal_value_a_service_passed_by_mistake(
    staff: User, member: User
) -> None:
    """The event layer is the last line: a future service that passes values still stores none."""
    with audit_context(channel=Channel.COMMAND, actor=staff), audited_atomic():
        event = record_event(
            USER_CHANGED,
            Change(
                "user",
                member.public_id,
                {"email": [member.email, f"{MARK}@example.org"], "is_staff": [False, True]},
            ),
        )
    event.refresh_from_db()
    assert event.changes == {"email": PERSONAL_CHANGED, "is_staff": [False, True]}
    assert events_holding(MARK) == []


def test_the_user_services_record_no_values_without_the_event_layer_mask(
    monkeypatch: pytest.MonkeyPatch, staff: User, member: User
) -> None:
    """The services own the rule; the mask in record_event() is only the last line behind it."""
    monkeypatch.setitem(PERSONAL_FIELDS, "user", ())
    with audit_context(channel=Channel.COMMAND, actor=staff):
        created = services.user_create(username=f"{MARK}-bare", password=None, email="b@x.org")
        services.user_update(user=member, changes={"first_name": f"{MARK} renamed"})
    changes = [e.changes for e in AuditEvent.objects.order_by("pk")]
    assert changes[-2:] == [
        {"username": "changed", "email": "changed", "has_usable_password": [None, False]},
        {"first_name": "changed"},
    ]
    assert events_holding(MARK) == []
    assert created.username == f"{MARK}-bare"
