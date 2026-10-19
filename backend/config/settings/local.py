import os

os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-not-a-secret-" + "x" * 40)
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")
os.environ.setdefault("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173")

from .base import *  # noqa: F403

# manage.py seed_dev fills the database with users that share a known password: it runs
# only where this is True. Only these settings set it, production.py sets it off.
DEV_DATA_ALLOWED = True

# Mail is printed to the runserver log, never sent.
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}
