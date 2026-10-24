import re
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.management import call_command
from django.templatetags.static import static
from django.test import Client, override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_api_responses_carry_security_headers(client: Client) -> None:
    response = client.get("/api/v1/auth/csrf/")
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in response["Permissions-Policy"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["X-Frame-Options"] == "DENY"
    assert response["Referrer-Policy"] == "same-origin"
    csp = {
        directive.split()[0]: directive.split()[1:]
        for directive in response["Content-Security-Policy"].split("; ")
    }
    assert csp == {
        "default-src": ["'none'"],
        "frame-ancestors": ["'none'"],
        "base-uri": ["'none'"],
        "form-action": ["'self'"],
    }


def test_options_does_not_describe_the_api(client: Client) -> None:
    # DEFAULT_METADATA_CLASS is None: no endpoint description for anonymous callers.
    assert client.options("/api/v1/auth/login/").status_code == 405


def policy_of(response: Any) -> dict[str, list[str]]:
    return {
        directive.split()[0]: directive.split()[1:]
        for directive in response["Content-Security-Policy"].split("; ")
    }


def test_admin_pages_may_load_their_own_styles_and_scripts(client: Client) -> None:
    # The API's policy (default-src 'none') blocked the admin's own CSS and JS.
    response = client.get(reverse("admin:login"))
    assert response.status_code == 200
    csp = policy_of(response)
    nonce = csp["script-src"][-1].removeprefix("'nonce-").removesuffix("'")
    assert len(nonce) >= 16
    assert csp["default-src"] == ["'none'"]
    assert csp["script-src"] == ["'self'", f"'nonce-{nonce}'"]
    assert csp["style-src"] == ["'self'", f"'nonce-{nonce}'"]
    assert csp["frame-ancestors"] == ["'none'"]
    # Django's admin templates put that nonce on every script and style they render, inline
    # or not, so nothing on the page is blocked.
    tags = re.findall(r"<(?:script|style)\b[^>]*>", response.content.decode())
    assert tags  # the page loads scripts, or this proves nothing
    assert all(f'nonce="{nonce}"' in tag for tag in tags)


def test_a_redirect_inside_the_admin_gets_the_admin_policy_and_the_api_keeps_its_own(
    client: Client,
) -> None:
    redirect = client.get(reverse("admin:index"))  # anonymous: to the login page
    assert redirect.status_code == 302
    assert "script-src" in policy_of(redirect)
    assert policy_of(client.get("/api/v1/auth/csrf/"))["default-src"] == ["'none'"]
    assert "script-src" not in policy_of(client.get("/api/v1/auth/csrf/"))


def test_the_collected_admin_files_are_served_by_the_app(tmp_path: Path) -> None:
    # The runtime image collects static files at build into a read-only tree that only the
    # app can read: WhiteNoise serves them, under hashed names with a far-future cache.
    storages = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    security = settings.MIDDLEWARE.index("django.middleware.security.SecurityMiddleware")
    middleware = [*settings.MIDDLEWARE]
    middleware.insert(security + 1, "whitenoise.middleware.WhiteNoiseMiddleware")
    with override_settings(STATIC_ROOT=tmp_path, STORAGES=storages, MIDDLEWARE=middleware):
        call_command("collectstatic", interactive=False, verbosity=0)
        url = static("admin/css/base.css")
        response = Client().get(url)  # a new client loads the middleware with this root
        assert url != "/static/admin/css/base.css"  # hashed by the manifest
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/css")
        assert "immutable" in response["Cache-Control"]
        response.close()
