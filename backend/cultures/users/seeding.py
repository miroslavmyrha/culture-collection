"""What seed_dev and seed_e2e make of users, through the services.

Found again by username, so a second run creates nobody twice. A user found is brought back to
what the seed names (active, with the seed's password or none), changed only where it differs.
"""

from . import services
from .models import User


def user(username: str, password: str | None) -> User:
    """An active user with this password (None: no usable one), changed only where needed."""
    found = User.objects.filter(username=username).first()
    if found is None:
        return services.user_create(username=username, password=password)
    if not found.is_active:
        found = services.user_activate(user=found)
    wrong = found.has_usable_password() if password is None else not found.check_password(password)
    if wrong:
        found = services.user_set_password(user=found, raw_password=password)
    return found


def superuser(username: str, password: str) -> None:
    """An active staff superuser with this password. A new one is made through
    User.objects.create_superuser, the project's superuser path (the services, with the audit
    context's reason)."""
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, password=password)
        return
    found = user(username, password)
    services.user_set_staff(user=found, is_staff=True)
    services.user_set_superuser(user=found, is_superuser=True)
