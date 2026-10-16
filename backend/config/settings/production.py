"""Production settings. Startup refuses configurations that are unsafe to serve."""

from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int

from .base import *  # noqa: F403
from .base import (
    ADMIN_PATH,
    ALLOWED_HOSTS,
    DEFAULT_ADMIN_PATH,
    NUM_PROXIES,
    SECRET_KEY,
    SECRET_KEY_FALLBACKS,
)

MIN_SECRET_KEY_LENGTH = 50
MIN_SECRET_KEY_UNIQUE_CHARS = 5
WEAK_SECRET_PREFIXES = ("dev-only", "test-only", "django-insecure", "change", "secret")


def _refuse_weak_secret(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) < MIN_SECRET_KEY_LENGTH
        or len(set(value)) < MIN_SECRET_KEY_UNIQUE_CHARS
        or value.lower().startswith(WEAK_SECRET_PREFIXES)
    ):
        raise ImproperlyConfigured(
            f"{name} must be a real random secret of at least {MIN_SECRET_KEY_LENGTH} characters."
        )


_refuse_weak_secret("DJANGO_SECRET_KEY", SECRET_KEY)
for _fallback in SECRET_KEY_FALLBACKS:
    _refuse_weak_secret("DJANGO_SECRET_KEY_FALLBACKS", _fallback)
if SECRET_KEY in SECRET_KEY_FALLBACKS:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must not also be listed in the fallbacks.")

if not ALLOWED_HOSTS or any(host.strip() in {"*", ".*"} for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list the real host names, never '*'.")

if ADMIN_PATH.strip("/") in {DEFAULT_ADMIN_PATH.strip("/"), "admin"}:
    raise ImproperlyConfigured("Set DJANGO_ADMIN_PATH to a non-default path such as 'ops-x7k2/'.")

DEBUG = False

# __Host- cookies: Secure, Path=/, no Domain, so a sibling subdomain cannot set
# or shadow them. The SPA reads the CSRF token from __Host-csrftoken.
SESSION_COOKIE_NAME = "__Host-sessionid"
CSRF_COOKIE_NAME = "__Host-csrftoken"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# HSTS preload is a one-way decision per domain: enable it deliberately. Its
# reminder (security.W021) is silenced so `check --deploy --fail-level WARNING`
# can gate deploys on every other warning.
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# One switch for the proxy: trust its scheme header, and require the number of
# proxies so the client IP for throttles is taken from the right hop.
BEHIND_TLS_PROXY = env_bool("DJANGO_BEHIND_TLS_PROXY", default=False)
if BEHIND_TLS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    if NUM_PROXIES < 1:
        raise ImproperlyConfigured(
            "DJANGO_BEHIND_TLS_PROXY is on: set DJANGO_NUM_PROXIES to the number of proxies "
            "that append to X-Forwarded-For (usually 1)."
        )
