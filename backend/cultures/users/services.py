"""Writes on users. Users are deactivated, never deleted: audit rows point at them.

Every function runs in audited_atomic() and records one event (record_batch for
many users). The actor, channel and request id come from the audit context:
the request in admin, audit_context() in commands. Privilege changes (active,
staff and superuser status) are their own event types and need a reason, which
the database also enforces (AuditEvent's reason check constraint). Password
changes record whether a usable password exists, never a value or a hash.

Validation of input (password rules, field formats) is the caller's job, as
in Django's forms and commands: these are the trusted writes behind them.

Deactivation keeps every lab with an active manager: it locks the users' rows
(by pk), then cultures.labs.services locks their labs (by pk) and refuses with
LastManager when a lab would have none left. Nothing is changed and nothing is
recorded then. The admin makes another member a manager first (ADR 0006).
"""

from collections.abc import Mapping, Sequence

from django.db import IntegrityError, transaction

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_batch, record_event
from cultures.audit.registry import (
    USER_ACTIVATED,
    USER_CHANGED,
    USER_CREATED,
    USER_DEACTIVATED,
    USER_LOGIN_LIMITS_CLEARED,
    USER_PASSWORD_CHANGED,
    USER_STAFF_CHANGED,
    USER_SUPERUSER_CHANGED,
    USERS_DEACTIVATED,
    EventType,
)
from cultures.core.exceptions import Conflict
from cultures.labs.services import users_deactivation_check

from . import login_limits
from .models import User

SUBJECT = "user"
# The fields user_update may change. Privileges and the password have their own services.
PROFILE_FIELDS = ("username", "first_name", "last_name", "email")
USERNAME_UNIQUE = "users_user_username_key"  # PostgreSQL's name for the field's unique=True


class UsernameTaken(Conflict):
    default_code = "username_taken"
    default_detail = "A user with this username already exists."


def _save(user: User, fields: list[str] | None = None) -> None:
    """Save in a savepoint, so a duplicate username is a Conflict, not a broken transaction."""
    try:
        with transaction.atomic():
            user.save(update_fields=fields)
    except IntegrityError as error:
        diag = getattr(error.__cause__, "diag", None)  # psycopg's error behind Django's
        if getattr(diag, "constraint_name", None) == USERNAME_UNIQUE:
            raise UsernameTaken(attr="username") from error
        raise


def _locked(user: User) -> User:
    return User.objects.select_for_update().get(pk=user.pk)


def user_create(
    *,
    username: str,
    password: str | None,
    email: str = "",
    first_name: str = "",
    last_name: str = "",
) -> User:
    """A new active user without privileges. password None: no usable password."""
    with audited_atomic():
        user = User(
            username=User.normalize_username(username),
            email=User.objects.normalize_email(email),
            first_name=first_name,
            last_name=last_name,
        )
        if password is None:
            user.set_unusable_password()
        else:
            user.set_password(password)
        _save(user)
        profile = {field: [None, getattr(user, field)] for field in PROFILE_FIELDS}
        record_event(
            USER_CREATED,
            Change(
                SUBJECT,
                user.public_id,
                {**profile, "has_usable_password": [None, user.has_usable_password()]},
            ),
        )
    return user


def user_update(*, user: User, changes: Mapping[str, str]) -> User:
    """Change profile fields. The event holds {field: [old, new]} of what really changed."""
    unknown = set(changes) - set(PROFILE_FIELDS)
    if unknown:
        raise ValueError(f"user_update changes only {PROFILE_FIELDS}, not {sorted(unknown)}")
    with audited_atomic():
        user = _locked(user)
        diff = {
            field: [getattr(user, field), value]
            for field, value in changes.items()
            if getattr(user, field) != value
        }
        if not diff:
            return user
        for field, (_, value) in diff.items():
            setattr(user, field, value)
        _save(user, list(diff))
        record_event(USER_CHANGED, Change(SUBJECT, user.public_id, diff))
    return user


def _set_flag(
    user: User, field: str, value: bool, event_type: EventType, reason: str | None
) -> User:
    """One privilege flag, with its event and reason. No change, no event."""
    with audited_atomic():
        user = _locked(user)
        old = getattr(user, field)
        if old == value:
            return user
        setattr(user, field, value)
        _save(user, [field])
        record_event(
            event_type, Change(SUBJECT, user.public_id, {field: [old, value]}), reason=reason
        )
    return user


def user_activate(*, user: User, reason: str | None = None) -> User:
    """Let a deactivated user sign in again. Needs a reason (from the argument or the context)."""
    return _set_flag(user, "is_active", True, USER_ACTIVATED, reason)


def user_set_staff(*, user: User, is_staff: bool, reason: str | None = None) -> User:
    """Grant or remove admin access. Needs a reason."""
    return _set_flag(user, "is_staff", is_staff, USER_STAFF_CHANGED, reason)


def user_set_superuser(*, user: User, is_superuser: bool, reason: str | None = None) -> User:
    """Grant or remove every Django permission. Needs a reason."""
    return _set_flag(user, "is_superuser", is_superuser, USER_SUPERUSER_CHANGED, reason)


def user_set_password(*, user: User, raw_password: str | None) -> User:
    """Set a new password, or none (raw_password None). The event never holds a value.

    Returns the saved user: a caller that keeps the session of this user (the
    admin changing its own password) needs its new session hash.
    """
    with audited_atomic():
        user = _locked(user)
        was_usable = user.has_usable_password()
        if raw_password is None:
            user.set_unusable_password()
        else:
            user.set_password(raw_password)
        _save(user, ["password"])
        record_event(
            USER_PASSWORD_CHANGED,
            Change(
                SUBJECT,
                user.public_id,
                {"has_usable_password": [was_usable, user.has_usable_password()]},
            ),
        )
    return user


def user_login_limits_clear(*, user: User, reason: str | None = None) -> int:
    """Delete the failed-login counters of the user's account: its pairs and its own count.

    For staff, when a user is held back (the account under attack, a pair in its
    back-off) and the wait must end now. The counters of the addresses stay: they
    count other accounts' failures too. Needs a reason, also when there was
    nothing to delete: the event records the decision. Returns how many counters
    were deleted.
    """
    with audited_atomic():
        deleted = login_limits.clear_account(user.username)
        record_event(
            USER_LOGIN_LIMITS_CLEARED,
            Change(SUBJECT, user.public_id, {"login_failure_counters": [deleted, 0]}),
            reason=reason,
        )
    return deleted


def user_deactivate(*, user: User, reason: str | None = None) -> User:
    """Deactivate one user. The actor and channel come from the audit context.

    Refused (LastManager) when the user is the last active manager of a lab.
    """
    with audited_atomic():
        user = _locked(user)
        users_deactivation_check(users=[user])
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
    """Deactivate many users with one UPDATE: one event per user plus a batch event.

    All or nothing: refused (LastManager) when together they are the last
    active managers of a lab, and then no user is deactivated.
    """
    with audited_atomic():
        locked = list(
            User.objects.select_for_update()
            .filter(pk__in=[u.pk for u in users], is_active=True)
            .order_by("pk")
        )
        users_deactivation_check(users=locked)
        User.objects.filter(pk__in=[u.pk for u in locked]).update(is_active=False)
        record_batch(
            USER_DEACTIVATED,
            USERS_DEACTIVATED,
            [Change(SUBJECT, u.public_id, {"is_active": [True, False]}) for u in locked],
            reason=reason,
        )
    return len(locked)


def superuser_create(
    *, username: str, password: str | None, email: str = "", reason: str | None = None
) -> User:
    """A user with staff and superuser status: three events in one transaction.

    The privileges go through user_set_staff and user_set_superuser, so they
    need a reason like any other grant. The user manager's create_superuser
    (and with it manage.py createsuperuser) calls this.
    """
    with audited_atomic():
        user = user_create(username=username, password=password, email=email)
        user = user_set_staff(user=user, is_staff=True, reason=reason)
        return user_set_superuser(user=user, is_superuser=True, reason=reason)
