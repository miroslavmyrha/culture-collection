import pytest
from django.conf import settings
from django.test import Client, override_settings
from model_bakery import baker
from pytest_django import DjangoAssertNumQueries

from cultures.users import login_limits
from cultures.users.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def user() -> User:
    u: User = baker.make(User, username="lab-tech")
    u.set_password("correct horse battery")
    u.save()
    return u


@pytest.fixture
def csrf_client() -> Client:
    """A client that enforces CSRF like a browser would."""
    return Client(enforce_csrf_checks=True)


def _csrf(client: Client) -> str:
    client.get("/api/v1/auth/csrf/")
    return client.cookies[settings.CSRF_COOKIE_NAME].value


def test_login_without_csrf_token_is_rejected(csrf_client: Client, user: User) -> None:
    response = csrf_client.post(
        "/api/v1/auth/login/",
        {"username": "lab-tech", "password": "correct horse battery"},
        content_type="application/json",
    )
    assert response.status_code == 403


def test_login_sets_session_and_me_works(
    csrf_client: Client, user: User, django_assert_max_num_queries: DjangoAssertNumQueries
) -> None:
    token = _csrf(csrf_client)
    response = csrf_client.post(
        "/api/v1/auth/login/",
        {"username": "lab-tech", "password": "correct horse battery"},
        content_type="application/json",
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 200
    assert response.json()["username"] == "lab-tech"
    assert "id" not in response.json()  # internal ids never leave the server
    with django_assert_max_num_queries(2):
        me = csrf_client.get("/api/v1/auth/me/")
    assert me.status_code == 200


def test_wrong_password_is_400(csrf_client: Client, user: User) -> None:
    token = _csrf(csrf_client)
    response = csrf_client.post(
        "/api/v1/auth/login/",
        {"username": "lab-tech", "password": "wrong"},
        content_type="application/json",
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_credentials"


def test_me_requires_login(client: Client) -> None:
    # 401, not 403: the SPA shows the login form on 401 and "not allowed" on 403.
    assert client.get("/api/v1/auth/me/").status_code == 401


def _login(client: Client, username: str, password: str, ip: str = "198.51.100.1") -> int:
    return client.post(
        "/api/v1/auth/login/",
        {"username": username, "password": password},
        content_type="application/json",
        REMOTE_ADDR=ip,
    ).status_code


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=5)
def test_account_limit_holds_across_addresses(client: Client, user: User) -> None:
    statuses = [_login(client, "lab-tech", "wrong", ip=f"203.0.113.{n}") for n in range(6)]
    assert statuses == [400] * 5 + [429]
    # While locked even the right password is refused, or guessing would go on.
    assert _login(client, "lab-tech", "correct horse battery", ip="192.0.2.9") == 429


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=3)
def test_account_limit_folds_case_and_blanks(client: Client, user: User) -> None:
    for name in ("lab-tech", "LAB-TECH", "Lab-Tech"):
        assert _login(client, name, "wrong") == 400
    assert _login(client, "lab-tech", "wrong") == 429


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=3)
def test_successful_login_clears_the_account_counter(client: Client, user: User) -> None:
    assert [_login(client, "lab-tech", "wrong") for _ in range(2)] == [400, 400]
    assert _login(client, "lab-tech", "correct horse battery") == 200
    Client().logout()
    assert [_login(Client(), "lab-tech", "wrong") for _ in range(3)] == [400, 400, 400]


@override_settings(LOGIN_ACCOUNT_MAX_FAILURES=2)
def test_unknown_accounts_are_limited_the_same_way(client: Client) -> None:
    assert [_login(client, "nobody", "x") for _ in range(3)] == [400, 400, 429]


def test_account_key_holds_no_username() -> None:
    key = login_limits.account_key("lab-tech")
    assert "lab-tech" not in key
    assert key == login_limits.account_key(" LAB-TECH ")
