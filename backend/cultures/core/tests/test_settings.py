"""Settings parsing and production startup refusals.

Production settings are imported in a fresh interpreter per case, because a
settings module runs its checks once at import.
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int, env_secret

BACKEND = Path(settings.BASE_DIR)
GOOD_KEY = secrets.token_urlsafe(64)
GOOD_ENV = {
    "DJANGO_SECRET_KEY": GOOD_KEY,
    "DJANGO_ALLOWED_HOSTS": "app.example.com",
    "DJANGO_ADMIN_PATH": "ops-x7k2/",
    "DATABASE_URL": "postgres://u:p@db:5432/app",
}


def load_production(env: dict[str, str], expr: str = "'ok'") -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 (fixed interpreter and arguments)
        [sys.executable, "-c", f"import config.settings.production as s; print({expr})"],
        cwd=BACKEND,
        env={"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_production_settings_load() -> None:
    result = load_production(GOOD_ENV, "s.DEBUG, s.SESSION_COOKIE_SECURE")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False True"


def test_production_cookies_use_host_prefix() -> None:
    result = load_production(GOOD_ENV, "s.SESSION_COOKIE_NAME, s.CSRF_COOKIE_NAME")
    assert result.stdout.split() == ["__Host-sessionid", "__Host-csrftoken"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"DJANGO_ALLOWED_HOSTS": ""}, "DJANGO_ALLOWED_HOSTS"),
        ({"DJANGO_ALLOWED_HOSTS": "*"}, "DJANGO_ALLOWED_HOSTS"),
        ({"DJANGO_ALLOWED_HOSTS": "app.example.com, *"}, "DJANGO_ALLOWED_HOSTS"),
        ({"DJANGO_ADMIN_PATH": "admin-local/"}, "DJANGO_ADMIN_PATH"),
        ({"DJANGO_ADMIN_PATH": "admin/"}, "DJANGO_ADMIN_PATH"),
        ({"DJANGO_SECRET_KEY": "short"}, "DJANGO_SECRET_KEY"),
        ({"DJANGO_SECRET_KEY": "django-insecure-" + "k" * 60}, "DJANGO_SECRET_KEY"),
        ({"DJANGO_SECRET_KEY": "ab" * 40}, "DJANGO_SECRET_KEY"),  # too few distinct characters
        ({"DJANGO_SECRET_KEY_FALLBACKS": "weak"}, "DJANGO_SECRET_KEY_FALLBACKS"),
        ({"DJANGO_SECRET_KEY_FALLBACKS": GOOD_KEY}, "fallbacks"),
        ({"DJANGO_BEHIND_TLS_PROXY": "true"}, "DJANGO_NUM_PROXIES"),
        ({"DJANGO_BEHIND_TLS_PROXY": "ture"}, "not a boolean"),
        ({"DJANGO_NUM_PROXIES": "one"}, "not an integer"),
        ({"LOG_FORMAT": "xml"}, "LOG_FORMAT"),
    ],
)
def test_production_refuses_unsafe_configuration(override: dict[str, str], message: str) -> None:
    result = load_production({**GOOD_ENV, **override})
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert message in result.stderr


def test_production_accepts_proxy_with_num_proxies() -> None:
    env = {**GOOD_ENV, "DJANGO_BEHIND_TLS_PROXY": "true", "DJANGO_NUM_PROXIES": "1"}
    result = load_production(env, "s.SECURE_PROXY_SSL_HEADER, s.REST_FRAMEWORK['NUM_PROXIES']")
    assert result.returncode == 0, result.stderr
    assert "1" in result.stdout


def test_secret_key_and_fallbacks_from_files(tmp_path: Path) -> None:
    key_file = tmp_path / "secret_key"
    key_file.write_text(GOOD_KEY + "\n")
    old = secrets.token_urlsafe(64)
    fallback_file = tmp_path / "fallbacks"
    fallback_file.write_text(old + "\n")
    env = {k: v for k, v in GOOD_ENV.items() if k != "DJANGO_SECRET_KEY"}
    env |= {
        "DJANGO_SECRET_KEY_FILE": str(key_file),
        "DJANGO_SECRET_KEY_FALLBACKS_FILE": str(fallback_file),
    }
    result = load_production(env, "repr((s.SECRET_KEY, s.SECRET_KEY_FALLBACKS))")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == repr((GOOD_KEY, [old]))


def test_shared_cache_outside_tests() -> None:
    from config.settings import base  # noqa: PLC0415

    assert base.CACHES["default"]["BACKEND"] == "django.core.cache.backends.db.DatabaseCache"
    assert "locmem" in str(settings.CACHES["default"]["BACKEND"]).lower()  # tests only


def test_default_throttles_cover_every_view() -> None:
    from config.settings import base  # noqa: PLC0415

    rest = base.REST_FRAMEWORK
    assert rest["DEFAULT_THROTTLE_CLASSES"]
    assert {"anon", "user", "login"} <= set(rest["DEFAULT_THROTTLE_RATES"])
    assert rest["NUM_PROXIES"] == 0


class TestEnvHelpers:
    @pytest.mark.parametrize(
        ("raw", "expected"), [("true", True), ("1", True), ("False", False), ("0", False)]
    )
    def test_env_bool_accepts_only_known_values(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
    ) -> None:
        monkeypatch.setenv("X_FLAG", raw)
        assert env_bool("X_FLAG", default=not expected) is expected

    @pytest.mark.parametrize("raw", ["ture", "yes", "on", "enabled"])
    def test_env_bool_refuses_anything_else(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        monkeypatch.setenv("X_FLAG", raw)
        with pytest.raises(ImproperlyConfigured, match="not a boolean"):
            env_bool("X_FLAG", default=False)

    def test_env_bool_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("X_FLAG", raising=False)
        assert env_bool("X_FLAG", default=True) is True

    def test_env_int_refuses_text_and_too_small(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("X_NUM", "ten")
        with pytest.raises(ImproperlyConfigured):
            env_int("X_NUM", default=1)
        monkeypatch.setenv("X_NUM", "-1")
        with pytest.raises(ImproperlyConfigured):
            env_int("X_NUM", default=1, minimum=0)

    def test_env_secret_strips_the_trailing_newline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "secret"
        path.write_text("x" * 60 + "\n")
        monkeypatch.delenv("X_SECRET", raising=False)
        monkeypatch.setenv("X_SECRET_FILE", str(path))
        assert env_secret("X_SECRET") == "x" * 60

    def test_env_secret_refuses_an_unreadable_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("X_SECRET", raising=False)
        monkeypatch.setenv("X_SECRET_FILE", "/nonexistent/secret")
        with pytest.raises(ImproperlyConfigured, match="not readable"):
            env_secret("X_SECRET", default="fallback")

    def test_env_secret_refuses_an_empty_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "secret"
        path.write_text("\n")
        monkeypatch.delenv("X_SECRET", raising=False)
        monkeypatch.setenv("X_SECRET_FILE", str(path))
        with pytest.raises(ImproperlyConfigured, match="empty"):
            env_secret("X_SECRET")

    def test_env_secret_refuses_both_sources(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "secret"
        path.write_text("a")
        monkeypatch.setenv("X_SECRET", "b")
        monkeypatch.setenv("X_SECRET_FILE", str(path))
        with pytest.raises(ImproperlyConfigured, match="not both"):
            env_secret("X_SECRET")

    def test_env_secret_falls_back_to_the_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("X_SECRET_FILE", raising=False)
        monkeypatch.setenv("X_SECRET", "value")
        assert env_secret("X_SECRET") == "value"
