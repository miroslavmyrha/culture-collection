"""Settings shared by every environment. Secrets and hosts come from the environment only.

Parsing is strict (config/env.py): an unknown boolean or integer stops startup.
Secrets can come from NAME_FILE (mounted secret files) instead of NAME.
"""

import re
from pathlib import Path
from typing import Any

import environ
from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

from config.env import env_bool, env_int, env_list, env_networks, env_secret, env_str

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = env_secret("DJANGO_SECRET_KEY")
# Old keys stay valid for sessions and signed values during a key rotation.
# Comma or newline separated (a secret file holds one key per line).
SECRET_KEY_FALLBACKS: list[str] = [
    key.strip()
    for key in re.split(r"[,\n]", env_secret("DJANGO_SECRET_KEY_FALLBACKS", ""))
    if key.strip()
]
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = env_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS: list[str] = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # Replaces "django.contrib.admin": the admin site with the API's login limits.
    "cultures.users.admin_apps.AdminConfig",
    # Before django.contrib.auth, so its createsuperuser and changepassword commands replace
    # Django's (the first app in this list wins) and write through the audited services.
    "cultures.users",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # BrinIndex on the audit tables (system check postgres.E005)
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "cultures.core",
    "cultures.labs",
    "cultures.audit",
    "cultures.taxonomy",
    "cultures.biosafety",
    "cultures.strains",
    "cultures.deposits",
    "cultures.lineage",
    "cultures.storage",
    "cultures.distribution",
]

MIDDLEWARE = [
    # First: probes answer before host validation, SSL redirect and sessions.
    "cultures.core.health.HealthCheckMiddleware",
    "cultures.core.request_id.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "cultures.core.middleware.PermissionsPolicyMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # The request becomes the audit context: events and row changes carry its user and id.
    "cultures.audit.context.AuditRequestMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.csp",
            ],
        },
    },
]

DATABASES = {"default": environ.Env.db_url_config(env_secret("DATABASE_URL"))}
DATABASES["default"]["ATOMIC_REQUESTS"] = False  # transactions belong in services
DATABASES["default"]["CONN_MAX_AGE"] = env_int("DB_CONN_MAX_AGE", default=60, minimum=0)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
# Stored on every audit_rowchange row: tells the app's writes from a psql session's.
# Set it per process kind (api, worker, migrate) where they run separately.
DATABASES["default"].setdefault("OPTIONS", {})["application_name"] = env_str(
    "DB_APPLICATION_NAME", "cultures"
)
# The roles of ADR 0005 (cultures/audit/roles.py): `manage.py db_roles` creates them,
# migrate as the migration role keeps their privileges, the app connects as the runtime role.
DATABASE_ROLES = {
    "audit_owner": env_str("DB_AUDIT_OWNER_ROLE", "cultures_audit"),
    "migration": env_str("DB_MIGRATION_ROLE", "cultures_migration"),
    "runtime": env_str("DB_RUNTIME_ROLE", "cultures_app"),
}
# /readyz fails while the app connects as a role that owns a table or may TRUNCATE
# one (core/health.py). Development runs as the owner, production requires it.
DB_RUNTIME_ROLE_REQUIRED = env_bool("DB_RUNTIME_ROLE_REQUIRED", default=False)

# One cache shared by all workers: throttles and login limits must not be per
# process. The table is created by `manage.py createcachetable` (deploy step).
# Switch to Redis when the project has one; test settings use LocMem.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 100_000},
    }
}

AUTH_USER_MODEL = "users.User"  # custom user from the first migration, see docs/decisions
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Login limits (cultures.users.login_limits): the request rate per address (DRF throttle
# scope "login"), then failed logins counted in a table, never a hard lock of an account:
# - per account and address bucket: after PAIR_MAX failures in the window, a back-off of
#   PAIR_BACKOFF seconds that doubles with each further failure, for that pair only;
# - per address bucket across accounts: ADDRESS_MAX failures, then the address waits;
# - per account across addresses: ACCOUNT_MAX failures put the account under attack, and
#   only a browser holding its known-device cookie may still try.
LOGIN_PAIR_MAX_FAILURES = env_int("LOGIN_PAIR_MAX_FAILURES", default=5, minimum=1)
LOGIN_PAIR_WINDOW_SECONDS = env_int("LOGIN_PAIR_WINDOW_SECONDS", default=15 * 60, minimum=1)
LOGIN_PAIR_BACKOFF_SECONDS = env_int("LOGIN_PAIR_BACKOFF_SECONDS", default=60, minimum=1)
LOGIN_ADDRESS_MAX_FAILURES = env_int("LOGIN_ADDRESS_MAX_FAILURES", default=30, minimum=1)
LOGIN_ADDRESS_WINDOW_SECONDS = env_int("LOGIN_ADDRESS_WINDOW_SECONDS", default=60 * 60, minimum=1)
LOGIN_ACCOUNT_MAX_FAILURES = env_int("LOGIN_ACCOUNT_MAX_FAILURES", default=20, minimum=1)
LOGIN_ACCOUNT_WINDOW_SECONDS = env_int("LOGIN_ACCOUNT_WINDOW_SECONDS", default=60 * 60, minimum=1)
# Set on every successful login: signed per account with the user's public id and
# password hash, so a password change revokes it. HttpOnly, SameSite=Lax, path /, no
# Domain. Production names it __Host- and makes it Secure, like the session cookie.
KNOWN_DEVICE_COOKIE_NAME = "knowndevice"
KNOWN_DEVICE_COOKIE_SECURE = False
KNOWN_DEVICE_COOKIE_AGE = 365 * 24 * 60 * 60

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Body limits. Django checks DATA_UPLOAD_MAX_MEMORY_SIZE when request.body is read,
# and DRF >= 3.17.2 parses JSON and form bodies from request.body, so JSON gets a
# 413 from Django. The API's JSON parser (cultures.core.parsers) caps its read too,
# as a second line. Django has no limit on multipart file size: the proxy's
# client_max_body_size is the cap.
DATA_UPLOAD_MAX_MEMORY_SIZE = env_int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=2 * 1024 * 1024)
DATA_UPLOAD_MAX_NUMBER_FIELDS = env_int("DATA_UPLOAD_MAX_NUMBER_FIELDS", default=1000)
DATA_UPLOAD_MAX_NUMBER_FILES = env_int("DATA_UPLOAD_MAX_NUMBER_FILES", default=20)
FILE_UPLOAD_MAX_MEMORY_SIZE = 0  # uploads stream to a temp file (tmpfs /tmp in the image)

# Session auth for the SPA: the session cookie is HttpOnly, the CSRF cookie is
# readable by the SPA, which sends it back in the X-CSRFToken header.
# Production renames both with the __Host- prefix (see production.py).
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", default=60 * 60 * 8, minimum=60)
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"

# The API serves JSON only; the frontend's own CSP is set where the SPA is served.
SECURE_CSP = {
    "default-src": [CSP.NONE],
    "frame-ancestors": [CSP.NONE],
    "base-uri": [CSP.NONE],
    "form-action": [CSP.SELF],
}
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Browser features the API never needs (cultures.core.middleware.PermissionsPolicyMiddleware).
PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
    "microphone=(), payment=(), usb=()"
)

# Email through Django 6.1's MAILERS. The old EMAIL_BACKEND, EMAIL_HOST and the
# other EMAIL_* connection settings are deprecated (RemovedInDjango2028Warning on
# every send) and refused next to MAILERS, so only the environment variables keep
# the old names. Without EMAIL_HOST, sending raises InvalidMailer ("OPTIONS must
# define 'host'") instead of trying localhost:25. Local and test settings replace it.
_email_options: dict[str, Any] = {
    "port": env_int("EMAIL_PORT", default=587, minimum=1),
    "username": env_str("EMAIL_HOST_USER", ""),
    "password": env_secret("EMAIL_HOST_PASSWORD", ""),
    "use_tls": env_bool("EMAIL_USE_TLS", default=True),
    "timeout": env_int("EMAIL_TIMEOUT", default=10, minimum=1),
}
if env_str("EMAIL_HOST", ""):
    _email_options["host"] = env_str("EMAIL_HOST", "")
MAILERS: dict[str, dict[str, Any]] = {
    "default": {"BACKEND": "django.core.mail.backends.smtp.EmailBackend", "OPTIONS": _email_options}
}
DEFAULT_FROM_EMAIL = env_str("DEFAULT_FROM_EMAIL", "webmaster@localhost")
SERVER_EMAIL = env_str("SERVER_EMAIL", DEFAULT_FROM_EMAIL)

DEFAULT_ADMIN_PATH = "admin-local/"
ADMIN_PATH = env_str("DJANGO_ADMIN_PATH", DEFAULT_ADMIN_PATH)

# Optional error reporting (Sentry-compatible SDK). Nothing is imported when empty.
ERROR_REPORTING_DSN = env_secret("ERROR_REPORTING_DSN", "")
ERROR_REPORTING_ENVIRONMENT = env_str("ERROR_REPORTING_ENVIRONMENT", "production")

# The proxies in front of the app, as addresses or networks (CIDR). X-Forwarded-For
# is read only on a request whose REMOTE_ADDR is one of them (cultures.core.client_ip).
# Empty: the header is ignored and REMOTE_ADDR is the client. gunicorn.conf.py gives
# gunicorn the same list as forwarded_allow_ips.
TRUSTED_PROXIES = env_networks("DJANGO_TRUSTED_PROXIES")

REST_FRAMEWORK: dict[str, Any] = {
    # 401 for anonymous requests (WWW-Authenticate: Session), 403 for "not allowed".
    "DEFAULT_AUTHENTICATION_CLASSES": ["cultures.core.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "cultures.core.parsers.LimitedJSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_SCHEMA_CLASS": "cultures.core.schema.AutoSchema",
    "DEFAULT_METADATA_CLASS": None,  # OPTIONS answers 405 instead of describing endpoints
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_PAGINATION_CLASS": "cultures.core.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "cultures.core.errors.exception_handler",
    # Every project throttle takes the client from cultures.core.client_ip (ClientIdentMixin).
    # 0 keeps DRF's own get_ident, should anything reach it, on REMOTE_ADDR.
    "NUM_PROXIES": 0,
    "DEFAULT_THROTTLE_CLASSES": [
        "cultures.core.throttling.AnonRateThrottle",
        "cultures.core.throttling.UserRateThrottle",
        "cultures.core.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env_str("THROTTLE_ANON", "100/hour"),
        "user": env_str("THROTTLE_USER", "2000/hour"),
        "login": env_str("THROTTLE_LOGIN", "10/min"),
    },
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "cultures API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,  # separate input and output schemas for generated TS types
    # One name per choice set, so the TS types have one Role, not one per field that uses it.
    "ENUM_NAME_OVERRIDES": {
        "Role": "cultures.labs.permissions.Role",
        "Pathogenicity": "cultures.strains.models.Pathogenicity",
        "RestrictionKind": "cultures.biosafety.models.RestrictionKind",
        "StrainStatus": "cultures.strains.models.StrainStatus",
        "TaxonStatus": "cultures.taxonomy.models.TaxonStatus",
        "RiskGroup": "cultures.strains.api.serializers.RISK_GROUPS",
        "CountryCode": "cultures.strains.api.serializers.COUNTRY_CHOICES",
        "DepositStatus": "cultures.deposits.models.DepositStatus",
        "Condition": "cultures.deposits.models.Condition",
        "AbsScope": "cultures.deposits.models.AbsScope",
        "Use": "cultures.deposits.models.Use",
        "Decision": "cultures.deposits.models.Decision",
        "UnitKind": "cultures.storage.models.UnitKind",
        "UnitStatus": "cultures.storage.models.UnitStatus",
        "VialStatus": "cultures.lineage.models.VialStatus",
        "PreservationMethod": "cultures.lineage.models.Method",
        "CheckKind": "cultures.lineage.models.CheckKind",
        "CheckStage": "cultures.lineage.models.CheckStage",
        "CheckMethod": "cultures.lineage.models.CheckMethod",
        "CheckResult": "cultures.lineage.models.CheckResult",
        "CheckUnit": "cultures.lineage.models.CheckUnit",
        "CheckStatus": "cultures.lineage.models.CheckStatus",
        "LegalForm": "cultures.distribution.models.LegalForm",
        "PermitKind": "cultures.distribution.models.PermitKind",
        "RequestStatus": "cultures.distribution.models.RequestStatus",
        "SignerRole": "cultures.distribution.models.SignerRole",
        "DocumentType": "cultures.distribution.models.DocumentType",
    },
}

LOG_FORMAT = env_str("LOG_FORMAT", "plain")
if LOG_FORMAT not in {"plain", "json"}:
    raise ImproperlyConfigured(f"LOG_FORMAT={LOG_FORMAT!r}: use plain or json.")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "cultures.core.request_id.RequestIdFilter"}},
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s"},
        "json": {"()": "cultures.core.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": LOG_FORMAT,
            "filters": ["request_id"],
        }
    },
    "root": {"handlers": ["console"], "level": env_str("LOG_LEVEL", "INFO")},
}
