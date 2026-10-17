"""The admin site: the API login's limits on its login, and the own password through a service.

The login has the same per-IP budget and the same account limit as the API login.
"""

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse

from config.settings import base
from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import assert_problem
from cultures.users.api.views import LoginThrottle
from cultures.users.models import User

from .conftest import PASSWORD, trail

pytestmark = pytest.mark.django_db
LOGIN = reverse("admin:login")
API_LOGIN = "/api/v1/auth/login/"
IP = "198.51.100.1"
NEW_PASSWORD = "a brand new admin password"  # noqa: S105 (a test password)


@pytest.fixture
def production_rate(monkeypatch: pytest.MonkeyPatch) -> str:
    """Test settings switch throttles off: put the production login rate back."""
    rate: str = base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]
    monkeypatch.setattr(LoginThrottle, "rate", rate, raising=False)
    return rate


def admin_login(client: Client, username: str, password: str, ip: str = IP) -> int:
    response = client.post(
        LOGIN, {"username": username, "password": password, "next": "/"}, REMOTE_ADDR=ip
    )
    return response.status_code


def signed_in(client: Client) -> bool:
    return client.get(reverse("admin:index")).status_code == 200


def test_the_eleventh_attempt_from_one_address_is_refused(
    production_rate: str, client: Client, staff: User
) -> None:
    assert production_rate == "10/min"
    # New names each time: this is the per-IP budget, not the account limit.
    assert [admin_login(client, f"guess{n}", "wrong") for n in range(10)] == [200] * 10
    response = client.post(LOGIN, {"username": "staff", "password": PASSWORD}, REMOTE_ADDR=IP)
    assert_problem(response, 429, "throttled")
    assert 0 < int(response["Retry-After"]) <= 60
    assert not signed_in(client)


def test_another_address_keeps_its_own_admin_login_budget(
    production_rate: str, client: Client, staff: User
) -> None:
    for n in range(10):
        admin_login(client, f"guess{n}", "wrong")
    assert admin_login(client, "staff", PASSWORD, ip="198.51.100.2") == 302
    assert signed_in(client)


def test_the_admin_and_the_api_login_share_one_budget_per_address(
    production_rate: str, client: Client
) -> None:
    for n in range(10):
        client.post(
            API_LOGIN,
            {"username": f"guess{n}", "password": "wrong"},
            content_type="application/json",
            REMOTE_ADDR=IP,
        )
    assert admin_login(client, "someone", "wrong") == 429


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=5)
def test_the_right_password_during_an_account_lock_is_refused_like_in_the_api(
    client: Client, staff: User
) -> None:
    statuses = [admin_login(client, "staff", "wrong", ip=f"203.0.113.{n}") for n in range(5)]
    assert statuses == [200] * 5
    response = client.post(LOGIN, {"username": "staff", "password": PASSWORD}, REMOTE_ADDR=IP)
    assert_problem(response, 429, "throttled")
    assert int(response["Retry-After"]) == settings.LOGIN_ACCOUNT_WINDOW_SECONDS
    assert not signed_in(client)
    # The API refuses it the same way: one lock per account, whichever door was used.
    api = client.post(
        API_LOGIN,
        {"username": "staff", "password": PASSWORD},
        content_type="application/json",
        REMOTE_ADDR=IP,
    )
    assert_problem(api, 429, "throttled")
    assert api["Retry-After"] == response["Retry-After"]


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=3)
def test_api_failures_count_for_the_admin_account_limit(client: Client, staff: User) -> None:
    for _ in range(3):
        client.post(
            API_LOGIN,
            {"username": "STAFF", "password": "wrong"},
            content_type="application/json",
        )
    assert admin_login(client, "staff", PASSWORD) == 429


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=3)
def test_a_successful_admin_login_clears_the_account_counter(client: Client, staff: User) -> None:
    assert [admin_login(client, "staff", "wrong") for _ in range(2)] == [200, 200]
    assert admin_login(client, "staff", PASSWORD) == 302
    assert [admin_login(Client(), "staff", "wrong") for _ in range(3)] == [200, 200, 200]


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=2)
def test_a_right_password_without_staff_status_counts_as_a_failure(client: Client) -> None:
    """The admin form refuses non-staff with the wrong-password message: the limit agrees."""
    member = User.objects.create_user("member", password=PASSWORD)
    assert [admin_login(client, "member", PASSWORD) for _ in range(3)] == [200, 200, 429]
    assert member.is_active


def test_the_login_page_itself_is_not_counted(production_rate: str, client: Client) -> None:
    assert {client.get(LOGIN, REMOTE_ADDR=IP).status_code for _ in range(12)} == {200}
    assert admin_login(client, "someone", "wrong") == 200


def test_staff_change_their_own_password_and_stay_signed_in(
    admin_client: Client, staff: User
) -> None:
    response = admin_client.post(
        reverse("admin:password_change"),
        {
            "old_password": PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )
    assert response.status_code == 302, response.content
    staff.refresh_from_db()
    assert staff.check_password(NEW_PASSWORD)
    (event,) = AuditEvent.objects.all()
    assert (event.event_type, event.actor, event.channel) == (
        "user_password_changed",
        staff,
        Channel.WEB,
    )
    # The session hash follows the new password, or the change would sign them out.
    assert admin_client.get(reverse("admin:index")).status_code == 200


def test_a_wrong_old_password_changes_nothing(admin_client: Client, staff: User) -> None:
    before = trail()
    response = admin_client.post(
        reverse("admin:password_change"),
        {"old_password": "wrong", "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
    )
    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.check_password(PASSWORD)
    assert trail() == before
