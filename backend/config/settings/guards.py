"""What the production settings refuse, in a module a test can import.

The settings modules run their checks at import, which a test can only reach in a fresh
interpreter, and a check reached that way is measured at no coverage (#205). The rules live
here instead, called from `production.py` at startup and from the tests directly.
"""

from django.core.exceptions import ImproperlyConfigured

MIN_SECRET_KEY_LENGTH = 50
MIN_SECRET_KEY_UNIQUE_CHARS = 5
WEAK_SECRET_PREFIXES = ("dev-only", "test-only", "django-insecure", "change", "secret")


def refuse_weak_secret(name: str, value: object) -> None:
    """A secret too short, too repetitive or carrying a placeholder prefix is no secret."""
    weak = (
        not isinstance(value, str)
        or len(value) < MIN_SECRET_KEY_LENGTH
        or len(set(value)) < MIN_SECRET_KEY_UNIQUE_CHARS
        or value.lower().startswith(WEAK_SECRET_PREFIXES)
    )
    if weak:
        raise ImproperlyConfigured(
            f"{name} must be a real random secret of at least {MIN_SECRET_KEY_LENGTH} characters."
        )


def refuse_open_hosts(hosts: list[str]) -> None:
    """A host list that is empty, or names every host, serves anyone who asks."""
    if not hosts or any(host.strip() in {"*", ".*"} for host in hosts):
        raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list the real host names, never '*'.")


def refuse_default_admin_path(path: str, default: str) -> None:
    """The admin at its default path is found by every scanner."""
    if path.strip("/") in {default.strip("/"), "admin"}:
        raise ImproperlyConfigured(
            "Set DJANGO_ADMIN_PATH to a non-default path such as 'ops-x7k2/'."
        )
