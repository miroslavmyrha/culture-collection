import os

import environ
from django.core.exceptions import ImproperlyConfigured

env = environ.Env()

# ruleid: environ-env-bool
DEBUG = env.bool("DEBUG", default=False)
# ruleid: environ-env-bool
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", cast=bool, default=True)


def strict_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw in ("1", "true"):
        return True
    if raw in ("0", "false"):
        return False
    raise ImproperlyConfigured(f"{name} must be true or false, got {raw!r}")


# ok: environ-env-bool
SESSION_COOKIE_SECURE = strict_bool("SESSION_COOKIE_SECURE", True)
