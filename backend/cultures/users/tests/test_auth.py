import pytest
from django.conf import settings
from django.test import Client
from model_bakery import baker

from cultures.core.testing import QueryBaseline, assert_problem, logged_in
from cultures.users.models import User

pytestmark = pytest.mark.django_db
LOGOUT = "/api/v1/auth/logout/"
ME = "/api/v1/auth/me/"


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
    assert_problem(response, 403, "permission_denied")
    assert settings.SESSION_COOKIE_NAME not in csrf_client.cookies
    assert_problem(csrf_client.get(ME), 401, "not_authenticated")


def test_login_sets_session_and_me_works(
    csrf_client: Client, user: User, query_baseline: QueryBaseline
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
    with query_baseline("auth_me"):
        me = csrf_client.get(ME)
    assert me.json() == response.json()


def test_wrong_password_is_400(csrf_client: Client, user: User) -> None:
    token = _csrf(csrf_client)
    response = csrf_client.post(
        "/api/v1/auth/login/",
        {"username": "lab-tech", "password": "wrong"},
        content_type="application/json",
        headers={"X-CSRFToken": token},
    )
    assert_problem(response, 400, "invalid_credentials")


def test_me_requires_login(client: Client) -> None:
    # 401, not 403: the SPA shows the login form on 401 and "not allowed" on 403.
    response = client.get(ME)
    assert_problem(response, 401, "not_authenticated")
    assert response["WWW-Authenticate"] == 'Session realm="api"'


def test_logout_ends_the_session(user: User) -> None:
    client = logged_in(user)
    assert client.get(ME).json()["username"] == "lab-tech"
    response = client.post(LOGOUT)
    assert response.status_code == 204
    assert_problem(client.get(ME), 401, "not_authenticated")


def test_logout_needs_a_session() -> None:
    assert_problem(logged_in(None).post(LOGOUT), 401, "not_authenticated")


def test_logout_needs_the_csrf_token(csrf_client: Client, user: User) -> None:
    csrf_client.force_login(user)
    assert_problem(csrf_client.post(LOGOUT), 403, "permission_denied")
    assert csrf_client.get(ME).json()["username"] == "lab-tech"  # still signed in


def test_logout_with_the_csrf_token_works(csrf_client: Client, user: User) -> None:
    csrf_client.force_login(user)
    response = csrf_client.post(LOGOUT, headers={"X-CSRFToken": _csrf(csrf_client)})
    assert response.status_code == 204
    assert_problem(csrf_client.get(ME), 401, "not_authenticated")
