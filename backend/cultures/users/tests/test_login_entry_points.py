"""Every way to log in goes through the login limits (cultures.users.login_limits).

The walk finds the login views in the URLconf: Django LoginView subclasses,
AdminSite.login, and every anonymous DRF view that accepts a POST (a new one
must be classified here: a login, or not a login with a reason). Each login
must then refuse the right password while its account is under attack, and
count a wrong one, so a door that skips the limiter fails here by name.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.admin import AdminSite
from django.contrib.auth.views import LoginView
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.permissions import AllowAny

from cultures.core.testing.contract import routed_api_views
from cultures.users import login_limits
from cultures.users.models import LoginFailures, User

from .conftest import PASSWORD
from .test_login_limits import admin, api, staff_user

pytestmark = pytest.mark.django_db

Door = Callable[..., str]
LOGIN_ENTRY_POINTS: dict[str, Door] = {
    "cultures.users.api.views.login_view": api,
    "admin:login": admin,
}
# Anonymous DRF views with POST that are no login, each with the reason.
NOT_LOGINS: dict[str, str] = {}


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
    assert sorted(found - set(LOGIN_ENTRY_POINTS)) == []
    assert sorted(set(LOGIN_ENTRY_POINTS) - found) == []  # no stale entries


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
