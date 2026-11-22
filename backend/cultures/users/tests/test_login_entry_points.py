"""Every way to log in goes through the login limits (cultures.users.login_limits).

The walk finds the login views in the URLconf: Django LoginView subclasses,
AdminSite.login, and every anonymous DRF view that accepts a POST (a new one
must be classified here: a login, or not a login with a reason). Each login
must then refuse the right password while its account is under attack, and
count a wrong one, so a door that skips the limiter fails here by name. Since #176 a
sign-in has two steps: the password, then the second factor (a code or a security key), each a
door here; the admin login checks no password and only sends visitors to the app's sign-in.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.auth.views import LoginView
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django.utils import timezone
from rest_framework.permissions import AllowAny

from cultures.core.testing.contract import routed_api_views
from cultures.users import login_limits
from cultures.users.models import LoginFailures, SecurityKey, User

from .conftest import PASSWORD
from .soft_key import SoftKey
from .test_login_limits import HOME, api, post_password, second, staff_user

pytestmark = pytest.mark.django_db

Door = Callable[..., str]


def key(client: Client, username: str, password: str, ip: str = HOME) -> str:
    """The security key as the door: the right password, then the key answers (#176), from the
    right origin for PASSWORD and from another one for anything else."""
    response = post_password(client, username, PASSWORD, ip)
    if response.status_code != 200:
        return {400: "wrong", 429: "limited"}[response.status_code]
    soft = SoftKey()
    user = User.objects.get(username=username)
    SecurityKey.objects.filter(user=user).delete()
    SecurityKey.objects.create(
        user=user, credential_id=soft.credential_id, public_key=soft.public_cose_key(), name="key"
    )
    origin = {"Origin": "http://localhost"}
    options = client.post(
        "/api/v1/auth/second-factor/key/options/",
        content_type="application/json",
        headers=origin,
        REMOTE_ADDR=ip,
    ).json()["options"]
    answer = soft.sign(options, origin=None if password == PASSWORD else "https://evil.example")
    signed = client.post(
        "/api/v1/auth/second-factor/key/",
        {"credential": answer},
        content_type="application/json",
        headers=origin,
        REMOTE_ADDR=ip,
    )
    return {200: "in", 422: "wrong", 429: "limited"}[signed.status_code]


LOGIN_ENTRY_POINTS: dict[str, Door] = {
    "cultures.users.api.views.login_view": api,
    "cultures.users.api.factor_views.second_factor_code": second,
    "cultures.users.api.factor_views.second_factor_key": key,
}
# Anonymous DRF views with POST that are no login, each with the reason.
NOT_LOGINS: dict[str, str] = {
    "cultures.users.api.factor_views.second_factor_key_options": (
        "a challenge for the key step, which counts the answer: no secret is checked here"
    ),
    "cultures.users.api.factor_views.key_registration_options": (
        "the first enrolment after the password step, for an account without a factor"
    ),
    "cultures.users.api.factor_views.key_enrol": (
        "the first enrolment after the password step: it adds a factor, it checks none"
    ),
    "cultures.users.api.factor_views.totp_setup": "a new secret for the first enrolment",
    "cultures.users.api.factor_views.enrolment_code": (
        "the manager's code before the first enrolment: it signs nobody in, and a wrong code"
        " counts in the login limits (test_enrolment_code.py)"
    ),
    "cultures.users.api.factor_views.totp_enrol": (
        "the first enrolment after the password step: the code proves the new app, not a person"
    ),
}
# Login views that read no password at all, each with what they do instead.
NO_PASSWORD: dict[str, str] = {
    "admin:login": "sends every visitor to the app's sign-in (cultures.users.admin_site)",
}


def _django_login_views(patterns: list[URLPattern | URLResolver], namespace: str = "") -> set[str]:
    found: set[str] = set()
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            inner = f"{namespace}{pattern.namespace}:" if pattern.namespace else namespace
            found |= _django_login_views(pattern.url_patterns, inner)
            continue
        callback = pattern.callback
        view_class = getattr(callback, "view_class", None)
        owner = getattr(callback, "__self__", None)
        is_admin_login = isinstance(owner, AdminSite) and callback.__name__ == "login"
        if is_admin_login or (isinstance(view_class, type) and issubclass(view_class, LoginView)):
            found.add(f"{namespace}{pattern.name}")
    return found


def login_views() -> set[str]:
    anonymous_posts = {
        name
        for name, cls in routed_api_views().items()
        if AllowAny in cls.permission_classes and "post" in set(dir(cls))
    }
    return (anonymous_posts - set(NOT_LOGINS)) | _django_login_views(get_resolver().url_patterns)


def test_every_login_view_is_a_known_entry_point() -> None:
    found = login_views()
    assert {"admin:login", "cultures.users.api.views.login_view"} <= found  # the walk works
    known = set(LOGIN_ENTRY_POINTS) | set(NO_PASSWORD)
    assert sorted(found - known) == []
    assert sorted(known - found) == []  # no stale entries


def test_the_admin_login_reads_no_password(alice: User) -> None:
    client = Client()
    response = client.post(reverse("admin:login"), {"username": "alice", "password": PASSWORD})
    assert (response.status_code, response.headers["Location"]) == (302, "/login")
    assert not LoginFailures.objects.exists()


@pytest.fixture
def alice() -> User:
    return staff_user("alice")


@pytest.mark.parametrize("name", sorted(LOGIN_ENTRY_POINTS))
def test_each_entry_point_refuses_the_right_password_under_attack(name: str, alice: User) -> None:
    now = timezone.now()
    LoginFailures.objects.create(
        account=login_limits.account_key("alice"),
        address="",
        window_ends_at=now + timedelta(minutes=30),
        last_failure_at=now,
        failures=20,
    )
    assert LOGIN_ENTRY_POINTS[name](Client(), "alice", PASSWORD) == "limited"


@pytest.mark.rule("R-ACCESS-03")
@pytest.mark.parametrize("name", sorted(LOGIN_ENTRY_POINTS))
def test_each_entry_point_counts_a_wrong_password(name: str, alice: User) -> None:
    assert LOGIN_ENTRY_POINTS[name](Client(), "alice", "wrong") == "wrong"
    (row,) = LoginFailures.objects.filter(account=login_limits.account_key("alice"), address="")
    assert row.failures == 1


@pytest.mark.parametrize("name", sorted(LOGIN_ENTRY_POINTS))
def test_each_entry_point_clears_its_pair_and_remembers_the_browser(name: str, alice: User) -> None:
    door, browser = LOGIN_ENTRY_POINTS[name], Client()
    assert door(browser, "alice", "wrong") == "wrong"
    assert door(browser, "alice", PASSWORD) == "in"
    account = login_limits.account_key("alice")
    assert not LoginFailures.objects.filter(account=account).exclude(address="").exists()
    assert browser.cookies[settings.KNOWN_DEVICE_COOKIE_NAME].value
