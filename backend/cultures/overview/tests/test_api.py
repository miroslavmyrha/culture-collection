"""The contract of Home's two reads (#69): no object in the URL, so no 404 or 403 to give. Anonymous
is 401, every signed-in person gets their own view (empty without a lab), and nothing writes."""

import pytest

from cultures.core.testing import assert_problem, logged_in
from cultures.labs.tests.conftest import make_user
from cultures.users.models import User

pytestmark = pytest.mark.django_db

# Spelled out: the contract coverage test finds them here (core/tests/test_contract_coverage.py).
OVERVIEW_URL = "/api/v1/me/overview/"
ACTIVITY_URL = "/api/v1/me/activity/"
URLS = [OVERVIEW_URL, ACTIVITY_URL]


@pytest.mark.parametrize("url", URLS)
def test_anonymous_gets_401_with_the_session_challenge(url: str) -> None:
    response = logged_in(None).get(url)
    assert_problem(response, 401, "not_authenticated")
    assert response["WWW-Authenticate"] == 'Session realm="api"'


@pytest.mark.parametrize("url", URLS)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_nothing_writes(url: str, method: str, curator: User) -> None:
    assert_problem(getattr(logged_in(None), method)(url), 401, "not_authenticated")
    assert_problem(getattr(logged_in(curator), method)(url), 405, "method_not_allowed")


def test_a_person_in_no_lab_gets_an_empty_view() -> None:
    client = logged_in(make_user("nobody"))
    assert client.get(OVERVIEW_URL).json() == {"waiting": [], "labs": []}
    assert client.get(ACTIVITY_URL).json() == {"results": []}
