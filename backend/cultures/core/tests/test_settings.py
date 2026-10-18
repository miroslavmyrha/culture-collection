"""Settings parsing and production startup refusals.

Production settings are imported in a fresh interpreter per case, because a
settings module runs its checks once at import.
"""

import ast
import functools
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def production_value(env: dict[str, str], expr: str) -> str:
    result = load_production(env, expr)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@functools.cache
def _refusal(override: tuple[tuple[str, str], ...]) -> str:
    result = load_production({**GOOD_ENV, **dict(override)})
    assert result.returncode != 0, override
    return result.stderr.strip().splitlines()[-1]


def refusal_line(override: dict[str, str]) -> str:
    """The exception line of a refused start. The traceback above it quotes source
    lines, so a message searched in the whole stderr is found even when it is gone."""
    return _refusal(tuple(sorted(override.items())))


def test_valid_production_settings_load() -> None:
    assert production_value(GOOD_ENV, "s.DEBUG, s.SESSION_COOKIE_SECURE") == "False True"


def test_production_requires_the_runtime_role_unless_turned_off() -> None:
    assert production_value(GOOD_ENV, "s.DB_RUNTIME_ROLE_REQUIRED") == "True"
    off = {**GOOD_ENV, "DB_RUNTIME_ROLE_REQUIRED": "false"}
    assert production_value(off, "s.DB_RUNTIME_ROLE_REQUIRED") == "False"


def test_production_forces_debug_off_even_when_the_env_asks() -> None:
    assert production_value({**GOOD_ENV, "DJANGO_DEBUG": "true"}, "s.DEBUG") == "False"


def test_production_cookies_use_host_prefix() -> None:
    names = production_value(GOOD_ENV, "s.SESSION_COOKIE_NAME, s.CSRF_COOKIE_NAME")
    assert names.split() == ["__Host-sessionid", "__Host-csrftoken"]


def test_session_cookie_is_http_only_and_same_site_lax() -> None:
    expr = "s.SESSION_COOKIE_HTTPONLY, s.SESSION_COOKIE_SAMESITE, s.CSRF_COOKIE_SAMESITE"
    assert production_value(GOOD_ENV, expr).split() == ["True", "Lax", "Lax"]


def test_production_redirects_to_https_with_a_year_of_hsts_by_default() -> None:
    value = production_value(GOOD_ENV, "s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS")
    assert value.split() == ["True", str(365 * 24 * 60 * 60)]


def test_body_limit_defaults_to_two_megabytes() -> None:
    value = production_value(GOOD_ENV, "s.DATA_UPLOAD_MAX_MEMORY_SIZE")
    assert value == str(2 * 1024 * 1024)


def test_mailer_uses_the_host_and_tls_from_the_environment() -> None:
    env = {**GOOD_ENV, "EMAIL_HOST": "smtp.example.com"}
    expr = "s.MAILERS['default']['BACKEND'], repr(s.MAILERS['default']['OPTIONS'])"
    backend, options = production_value(env, expr).split(" ", 1)
    assert backend == "django.core.mail.backends.smtp.EmailBackend"
    assert ast.literal_eval(options) == {
        "host": "smtp.example.com",
        "port": 587,
        "username": "",
        "password": "",
        "use_tls": True,
        "timeout": 10,
    }


REFUSALS: list[tuple[dict[str, str], str]] = [
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
    ({"DJANGO_BEHIND_TLS_PROXY": "true"}, "set DJANGO_TRUSTED_PROXIES"),
    ({"DJANGO_BEHIND_TLS_PROXY": "ture"}, "not a boolean"),
    ({"DJANGO_NUM_PROXIES": "1"}, "DJANGO_NUM_PROXIES is gone"),
    ({"DJANGO_TRUSTED_PROXIES": "10.0.0.5/24"}, "DJANGO_TRUSTED_PROXIES"),
    ({"DJANGO_TRUSTED_PROXIES": "0.0.0.0/0"}, "would trust every client"),
    ({"LOG_FORMAT": "xml"}, "LOG_FORMAT"),
]


@pytest.mark.parametrize(("override", "message"), REFUSALS)
def test_production_refuses_unsafe_configuration(override: dict[str, str], message: str) -> None:
    line = refusal_line(override)
    assert line.startswith("django.core.exceptions.ImproperlyConfigured: "), line
    assert message in line


def _production_refusal_patterns() -> list[re.Pattern[str]]:
    """The message of every ImproperlyConfigured raised in production.py, as a regex."""
    tree = ast.parse((BACKEND / "config/settings/production.py").read_text())
    patterns = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ImproperlyConfigured":
            message: Any = node.args[0]
            parts = message.values if isinstance(message, ast.JoinedStr) else [message]
            patterns.append(
                re.compile(
                    "".join(
                        re.escape(str(part.value)) if isinstance(part, ast.Constant) else ".*"
                        for part in parts
                    )
                )
            )
    return patterns


def test_every_production_refusal_has_a_case() -> None:
    patterns = _production_refusal_patterns()
    assert patterns  # an empty walk must not pass
    lines = [refusal_line(override) for override, _ in REFUSALS]
    untested = [p.pattern for p in patterns if not any(p.search(line) for line in lines)]
    assert untested == [], "add a case to REFUSALS for each of these refusals"


def test_production_accepts_a_proxy_with_its_trusted_addresses() -> None:
    env = {
        **GOOD_ENV,
        "DJANGO_BEHIND_TLS_PROXY": "true",
        "DJANGO_TRUSTED_PROXIES": "10.0.0.5, 10.1.0.0/16",
    }
    expr = "repr(s.SECURE_PROXY_SSL_HEADER), *s.TRUSTED_PROXIES, s.REST_FRAMEWORK['NUM_PROXIES']"
    # Only "https" in the proxy's scheme header marks a request as secure. DRF's own
    # hop count stays 0: the project's throttles read cultures.core.client_ip.
    assert production_value(env, expr) == (
        "('HTTP_X_FORWARDED_PROTO', 'https') 10.0.0.5/32 10.1.0.0/16 0"
    )


def test_production_without_a_proxy_trusts_no_forwarding_header() -> None:
    assert (
        production_value(GOOD_ENV, "s.TRUSTED_PROXIES, getattr(s, 'SECURE_PROXY_SSL_HEADER', None)")
        == "() None"
    )


def test_secret_key_and_fallbacks_from_files(tmp_path: Path) -> None:
    key_file = tmp_path / "secret_key"
    key_file.write_text(GOOD_KEY + "\n")
    old, older = secrets.token_urlsafe(64), secrets.token_urlsafe(64)
    fallback_file = tmp_path / "fallbacks"
    fallback_file.write_text(f"{old}\n{older}\n")  # one key per line
    env = {k: v for k, v in GOOD_ENV.items() if k != "DJANGO_SECRET_KEY"}
    env |= {
        "DJANGO_SECRET_KEY_FILE": str(key_file),
        "DJANGO_SECRET_KEY_FALLBACKS_FILE": str(fallback_file),
    }
    value = production_value(env, "repr((s.SECRET_KEY, s.SECRET_KEY_FALLBACKS))")
    assert value == repr((GOOD_KEY, [old, older]))


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

    def test_env_bool_treats_a_blank_value_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("X_FLAG", "  ")
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


# Every environment read goes through config/env.py, so every value is parsed strictly.
ENV_PARSER = BACKEND / "config" / "env.py"
ENV_READ_CALLS = {("os", "getenv"), ("environ", "get"), ("environ", "pop")}


def _reads_environment(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript):  # os.environ["X"]
        value = node.value
        return isinstance(value, ast.Attribute) and value.attr == "environ"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        owner = node.func.value
        owner_name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
        return (owner_name, node.func.attr) in ENV_READ_CALLS
    return False


def environment_reads(path: Path) -> list[str]:
    return [
        f"{path.relative_to(BACKEND)}:{getattr(node, 'lineno', '?')}"
        for node in ast.walk(ast.parse(path.read_text()))
        if _reads_environment(node) and not isinstance(getattr(node, "ctx", None), ast.Store)
    ]


def test_every_environment_read_goes_through_config_env() -> None:
    # Tests and test tools read their own switches (UPDATE_QUERY_COUNTS), and
    # gunicorn.conf.py runs before Django, outside config/ and cultures/.
    sources = [
        path
        for path in [*BACKEND.glob("config/**/*.py"), *BACKEND.glob("cultures/**/*.py")]
        if path != ENV_PARSER and not {"tests", "testing"} & set(path.parts)
    ]
    assert ENV_PARSER.is_file() and environment_reads(ENV_PARSER)  # the walk can see a read
    assert [read for path in sources for read in environment_reads(path)] == []
