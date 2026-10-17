"""Writes on users. Users are deactivated, never deleted: audit rows point at them."""

from collections.abc import Sequence

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_batch, record_event
from cultures.audit.registry import USER_DEACTIVATED, USERS_DEACTIVATED

from .models import User

SUBJECT = "user"


def user_deactivate(*, user: User, reason: str | None = None) -> User:
    """Deactivate one user. The actor and channel come from the audit context."""
    with audited_atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        was_active = user.is_active
        user.is_active = False
        user.save(update_fields=["is_active"])
        record_event(
            USER_DEACTIVATED,
            Change(SUBJECT, user.public_id, {"is_active": [was_active, False]}),
            reason=reason,
        )
    return user


def users_deactivate(*, users: Sequence[User], reason: str | None = None) -> int:
    """Deactivate many users with one UPDATE: one event per user plus a batch event."""
    with audited_atomic():
        locked = list(
            User.objects.select_for_update()
            .filter(pk__in=[u.pk for u in users], is_active=True)
            .order_by("pk")
        )
        User.objects.filter(pk__in=[u.pk for u in locked]).update(is_active=False)
        record_batch(
            USER_DEACTIVATED,
            USERS_DEACTIVATED,
            [Change(SUBJECT, u.public_id, {"is_active": [True, False]}) for u in locked],
            reason=reason,
        )
    return len(locked)
