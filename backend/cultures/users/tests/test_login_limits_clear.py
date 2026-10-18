"""Staff clear an account's login limits: an audited service with a reason, in the user admin."""

from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, Channel
from cultures.core.exceptions import RuleViolation
from cultures.users import login_limits, services
from cultures.users.admin import REASON_REQUIRED
from cultures.users.models import LoginFailures, User

from .conftest import PASSWORD, trail
from .test_admin import form_of
from .test_login_limits import HOME, NEW, api, put_under_attack, staff_user

pytestmark = pytest.mark.django_db
REASON = "called the help desk, confirmed by phone"


@pytest.fixture
def alice() -> User:
    return staff_user("Alice")


def counts() -> dict[tuple[str, str], int]:
    return {(row.account, row.address): row.failures for row in LoginFailures.objects.all()}


def test_clearing_ends_the_attack_for_every_browser(alice: User, audited: AuditContext) -> None:
    put_under_attack(api, "alice")  # typed in lower case: the same account
    assert api(Client(), "Alice", PASSWORD, NEW) == "limited"
    deleted = services.user_login_limits_clear(user=alice, reason=REASON)
    assert deleted == 1 + 20  # the account's own counter and one pair per address
    assert api(Client(), "Alice", PASSWORD, NEW) == "in"


def test_the_address_counters_stay(alice: User, audited: AuditContext) -> None:
    api(Client(), "alice", "wrong", HOME)
    services.user_login_limits_clear(user=alice, reason=REASON)
    assert counts() == {("", login_limits.address_key(HOME)): 1}


def test_the_event_names_the_staff_actor_the_reason_and_the_count(
    alice: User, staff: User, audited: AuditContext
) -> None:
    api(Client(), "alice", "wrong", HOME)
    services.user_login_limits_clear(user=alice, reason=REASON)
    (event,) = AuditEvent.objects.filter(event_type="user_login_limits_cleared")
    assert (event.actor, event.reason, event.subject_id) == (staff, REASON, alice.public_id)
    assert event.changes == {"login_failure_counters": [2, 0]}


def test_nothing_to_clear_still_records_the_decision(alice: User, audited: AuditContext) -> None:
    assert services.user_login_limits_clear(user=alice, reason=REASON) == 0
    (event,) = AuditEvent.objects.filter(event_type="user_login_limits_cleared")
    assert event.changes == {"login_failure_counters": [0, 0]}


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_without_a_reason_nothing_is_cleared(
    alice: User, audited: AuditContext, reason: str | None
) -> None:
    api(Client(), "alice", "wrong", HOME)
    before, events = counts(), trail()
    with pytest.raises(RuleViolation) as refused:
        services.user_login_limits_clear(user=alice, reason=reason)
    assert refused.value.code == "reason_required"
    assert counts() == before
    assert trail() == events


def change_url(user: User) -> str:
    return reverse("admin:users_user_change", args=[user.pk])


def test_staff_clear_from_the_change_form(admin_client: Client, staff: User, alice: User) -> None:
    put_under_attack(api, "alice")
    page = admin_client.get(change_url(alice))
    assert "20: under attack until" in page.content.decode()
    response = admin_client.post(
        change_url(alice),
        form_of(alice, clear_login_limits=True, reason=REASON),
        headers={"X-Request-ID": "adm-clear"},
    )
    assert response.status_code == 302, response.content
    (event,) = AuditEvent.objects.filter(event_type="user_login_limits_cleared")
    assert (event.actor, event.channel, event.request_id, event.reason) == (
        staff,
        Channel.WEB,
        "adm-clear",
        REASON,
    )
    assert not LoginFailures.objects.filter(account=login_limits.account_key("alice")).exists()
    assert "none in the last window" in admin_client.get(change_url(alice)).content.decode()


def test_the_change_form_refuses_a_clear_without_a_reason(
    admin_client: Client, alice: User
) -> None:
    api(Client(), "alice", "wrong", HOME)
    before = counts()
    response = admin_client.post(change_url(alice), form_of(alice, clear_login_limits=True))
    assert response.status_code == 200
    assert REASON_REQUIRED in response.content.decode()
    assert counts() == before
    assert not AuditEvent.objects.filter(event_type="user_login_limits_cleared").exists()


def test_the_change_form_shows_a_count_below_the_attack(admin_client: Client, alice: User) -> None:
    now = timezone.now()
    LoginFailures.objects.create(
        account=login_limits.account_key("alice"),
        address="",
        window_ends_at=now + timedelta(minutes=5),
        last_failure_at=now,
        failures=3,
    )
    page = admin_client.get(change_url(alice)).content.decode()
    assert f"3 until {now + timedelta(minutes=5):%Y-%m-%d %H:%M} UTC" in page
