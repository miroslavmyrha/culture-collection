"""The production settings refuse a configuration that would ship a weak secret or an open host.

Each guard is checked in a fresh interpreter, because a settings module runs its checks at
import. The dev settings never reach these lines, so without this file the guards were measured
at no coverage at all (#205).
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.settings.guards import (
    refuse_default_admin_path,
    refuse_open_hosts,
    refuse_weak_secret,
)

BACKEND = Path(settings.BASE_DIR)
STRONG = secrets.token_urlsafe(64)
SOUND_ENV = {
    "DJANGO_SECRET_KEY": STRONG,
    "DJANGO_ALLOWED_HOSTS": "app.example.com",
    "DJANGO_ADMIN_PATH": "ops-x7k2/",
    "DATABASE_URL": "postgres://u:p@db:5432/app",
}
LOAD = "import django; django.setup(); print('loaded')"


def _load(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = {**SOUND_ENV, **overrides}
    return subprocess.run(  # noqa: S603 (fixed interpreter and arguments)
        [sys.executable, "-c", LOAD],
        cwd=BACKEND,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            **{k: v for k, v in env.items() if v is not None},
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_sound_configuration_loads() -> None:
    result = _load()
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "loaded"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param(
            {"DJANGO_SECRET_KEY": "short"}, "must be a real random secret", id="too-short"
        ),
        pytest.param(
            {"DJANGO_SECRET_KEY": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
            "must be a real random secret",
            id="too-few-characters",
        ),
        pytest.param(
            {"DJANGO_SECRET_KEY": "django-insecure-" + "x7Qp2" * 12},
            "must be a real random secret",
            id="the-django-placeholder",
        ),
        pytest.param(
            {"DJANGO_SECRET_KEY_FALLBACKS": "dev-only-secret"},
            "must be a real random secret",
            id="a-weak-fallback",
        ),
        pytest.param(
            {"DJANGO_SECRET_KEY_FALLBACKS": STRONG},
            "must not also be listed in the fallbacks",
            id="the-key-as-its-own-fallback",
        ),
        pytest.param({"DJANGO_ALLOWED_HOSTS": ""}, "never '*'", id="no-host"),
        pytest.param({"DJANGO_ALLOWED_HOSTS": "*"}, "never '*'", id="every-host"),
        pytest.param(
            {"DJANGO_ALLOWED_HOSTS": "app.example.com, *"},
            "never '*'",
            id="every-host-among-others",
        ),
        pytest.param(
            {"DJANGO_ADMIN_PATH": "admin/"}, "non-default path", id="the-default-admin-path"
        ),
        pytest.param(
            {"AUDIT_TIMESTAMP_BACKEND": "cultures.audit.timestamping.FakeAuthority"},
            "must not be the fake timestamp authority",
            id="the-fake-timestamp-authority",
        ),
        pytest.param(
            {"DJANGO_NUM_PROXIES": "1"}, "DJANGO_NUM_PROXIES is gone", id="the-old-hop-count"
        ),
        pytest.param(
            {"DJANGO_BEHIND_TLS_PROXY": "1"},
            "set DJANGO_TRUSTED_PROXIES",
            id="a-proxy-without-its-addresses",
        ),
    ],
)
def test_the_production_settings_refuse(overrides: dict[str, str], message: str) -> None:
    result = _load(**overrides)
    assert result.returncode != 0, result.stdout
    assert "ImproperlyConfigured" in result.stderr
    assert message in result.stderr


def test_a_proxy_with_its_addresses_loads() -> None:
    result = _load(DJANGO_BEHIND_TLS_PROXY="1", DJANGO_TRUSTED_PROXIES="10.0.0.0/8")
    assert result.returncode == 0, result.stderr[-2000:]


# The rules themselves, called in this process, so what they refuse is measured and not only
# proven through a fresh interpreter above.


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("short", id="too-short"),
        pytest.param("a" * 60, id="too-few-characters"),
        pytest.param("django-insecure-" + "x7Qp2" * 12, id="the-django-placeholder"),
        pytest.param("dev-only-" + "x7Qp2" * 12, id="a-dev-prefix"),
        pytest.param("secret" + "x7Qp2" * 12, id="the-word-secret"),
        pytest.param(None, id="not-a-string"),
    ],
)
def test_refuse_weak_secret_refuses(value: object) -> None:
    with pytest.raises(ImproperlyConfigured, match="must be a real random secret"):
        refuse_weak_secret("DJANGO_SECRET_KEY", value)


def test_refuse_weak_secret_accepts_a_real_one() -> None:
    refuse_weak_secret("DJANGO_SECRET_KEY", STRONG)


@pytest.mark.parametrize(
    "hosts",
    [
        pytest.param([], id="empty"),
        pytest.param(["*"], id="star"),
        pytest.param([".*"], id="dot-star"),
        pytest.param(["app.example.com", " * "], id="star-among-others"),
    ],
)
def test_refuse_open_hosts_refuses(hosts: list[str]) -> None:
    with pytest.raises(ImproperlyConfigured, match="never"):
        refuse_open_hosts(hosts)


def test_refuse_open_hosts_accepts_real_names() -> None:
    refuse_open_hosts(["app.example.com", "collection.example.org"])


@pytest.mark.parametrize(
    "path", [pytest.param("admin/", id="admin"), pytest.param("ops/", id="the-default")]
)
def test_refuse_default_admin_path_refuses(path: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="non-default path"):
        refuse_default_admin_path(path, "ops/")


def test_refuse_default_admin_path_accepts_another() -> None:
    refuse_default_admin_path("ops-x7k2/", "ops/")
