"""The admin site: its sign-in is the app's (#176), and the own password goes through a service.

The admin has no password form of its own any more: every sign-in takes a second factor, so a
visitor is sent to the app's sign-in, whose limits test_login_limits.py checks on both steps.
"""

import pytest
from django.test import Client
from django.urls import reverse

from cultures.audit.models import AuditEvent, Channel
from cultures.users.models import LoginFailures, User

from .conftest import PASSWORD, trail

pytestmark = pytest.mark.django_db
LOGIN = reverse("admin:login")
NEW_PASSWORD = "a brand new admin password"  # noqa: S105 (a test password)


def test_the_admin_login_sends_a_visitor_to_the_app_sign_in(client: Client) -> None:
    response = client.get(LOGIN)
    assert (response.status_code, response.headers["Location"]) == (302, "/login")


def test_a_password_posted_to_the_admin_is_never_checked(client: Client, staff: User) -> None:
    response = client.post(LOGIN, {"username": "staff", "password": PASSWORD, "next": "/"})
    assert (response.status_code, response.headers["Location"]) == (302, "/login")
    assert "_auth_user_id" not in client.session
    wrong = client.post(LOGIN, {"username": "staff", "password": "wrong"})
    assert wrong.status_code == 302
    assert not LoginFailures.objects.exists()  # nothing to count: no password was read


def test_signed_in_staff_go_to_the_index(admin_client: Client) -> None:
    response = admin_client.get(LOGIN)
    assert (response.status_code, response.headers["Location"]) == (302, reverse("admin:index"))
    assert admin_client.get(reverse("admin:index")).status_code == 200


def test_a_staff_session_without_a_second_factor_reaches_nothing(staff: User) -> None:
    client = Client()
    client.force_login(staff)  # no second factor: signed out before the admin runs
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert response.headers["Location"].startswith(LOGIN)


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
