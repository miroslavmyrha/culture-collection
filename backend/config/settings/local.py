import os

os.environ.setdefault("DJANGO_SECRET_KEY", "dev-only-not-a-secret-" + "x" * 40)
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")
os.environ.setdefault("DJANGO_CSRF_TRUSTED_ORIGINS", "http://localhost:5173")

from .base import *  # noqa: F403

# Mail is printed to the runserver log, never sent.
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}
