import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def test_api_responses_carry_security_headers(client: Client) -> None:
    response = client.get("/api/v1/auth/csrf/")
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in response["Permissions-Policy"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in response["Content-Security-Policy"]


def test_options_does_not_describe_the_api(client: Client) -> None:
    # DEFAULT_METADATA_CLASS is None: no endpoint description for anonymous callers.
    assert client.options("/api/v1/auth/login/").status_code == 405
