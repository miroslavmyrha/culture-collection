"""Where a security key operation may come from (#176): from settings in production, the
request's own localhost origin only where local and test settings allow it."""

import pytest
from django.test import RequestFactory
from pytest_django.fixtures import Settings

from cultures.users.factors import KeyRefused
from cultures.users.signin import site

SERVED = ["https://collection.example.org", "https://www.collection.example.org"]


@pytest.fixture
def production(settings: Settings) -> Settings:
    settings.WEBAUTHN_ALLOW_LOCALHOST = False
    settings.WEBAUTHN_ORIGINS = SERVED
    settings.WEBAUTHN_RP_ID = "collection.example.org"
    return settings


def test_the_configured_origins_and_relying_party_win_over_the_request(
    production: Settings,
) -> None:
    request = RequestFactory().post("/", HTTP_ORIGIN="https://evil.example")
    assert site(request) == ("collection.example.org", SERVED)


def test_without_a_relying_party_id_the_first_origin_names_it(production: Settings) -> None:
    production.WEBAUTHN_RP_ID = ""
    assert site(RequestFactory().post("/")) == ("collection.example.org", SERVED)


def test_nothing_configured_and_no_localhost_refuses(settings: Settings) -> None:
    settings.WEBAUTHN_ORIGINS, settings.WEBAUTHN_ALLOW_LOCALHOST = [], False
    with pytest.raises(KeyRefused) as refused:
        site(RequestFactory().post("/", HTTP_ORIGIN="http://localhost:5173"))
    assert refused.value.detail == (
        "Security keys are not set up on this server (WEBAUTHN_ORIGINS)."
    )


@pytest.fixture
def local(settings: Settings) -> Settings:
    settings.WEBAUTHN_ORIGINS, settings.WEBAUTHN_ALLOW_LOCALHOST = [], True
    settings.ALLOWED_HOSTS = ["localhost"]
    return settings


@pytest.mark.usefixtures("local")
def test_locally_the_requests_localhost_origin_is_taken() -> None:
    request = RequestFactory().post("/", HTTP_ORIGIN="http://localhost:5173")
    assert site(request) == ("localhost", ["http://localhost:5173"])


@pytest.mark.usefixtures("local")
def test_locally_without_an_origin_header_the_request_host_is_used() -> None:
    request = RequestFactory().post("/", HTTP_HOST="localhost:8000")
    assert site(request) == ("localhost", ["http://localhost:8000"])


@pytest.mark.usefixtures("local")
def test_locally_another_host_is_refused() -> None:
    with pytest.raises(KeyRefused):
        site(RequestFactory().post("/", HTTP_ORIGIN="https://evil.example"))
