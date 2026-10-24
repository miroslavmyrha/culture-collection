import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret-" + "x" * 40)
os.environ.setdefault("DATABASE_URL", "postgres://cultures:cultures@localhost:5432/cultures")

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK as BASE_REST_FRAMEWORK

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only, tests never ship
NO_THROTTLE_RATES = {"login": None, "user": None, "anon": None}
REST_FRAMEWORK = {
    **BASE_REST_FRAMEWORK,
    # Tests that exercise a throttle set its rate themselves.
    "DEFAULT_THROTTLE_RATES": NO_THROTTLE_RATES,
}

# Mail stays in django.core.mail.outbox (the test runner sets locmem for every alias too).
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}

# Tests connect as the owner. tests/test_health.py turns the check on where it tests it.
DB_RUNTIME_ROLE_REQUIRED = False

# Per-process cache only here: production shares one cache between workers.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Migration safety lint (manage.py lintmigrations), only needed where checks run.
INSTALLED_APPS = [*INSTALLED_APPS, "django_migration_linter"]  # noqa: F405
# Migrations the linter skips, by name, each with its reason in its docstring. Never an
# IgnoreMigration operation: a migration that imports the linter cannot load in the runtime
# image, which has no dev dependencies (core/tests/test_production_imports.py).
MIGRATION_LINTER_OPTIONS = {"ignore_name": ["0006_request_status_length"]}
