"""Registries of the audit trail: event types and the tables the row trigger watches.

This module imports no models, so models.py can build its constraints from it.

Event types: every code a service may record, with a timeline template. A code
registered twice raises at import. The types that need a reason are also a
check constraint on AuditEvent: adding one changes that constraint, and
`makemigrations --check` in check.sh fails until the migration exists. On a
large audit table write that migration as NOT VALID plus VALIDATE (RunSQL in
SeparateDatabaseAndState), because a plain AddConstraint scans the table under
an ACCESS EXCLUSIVE lock.

Row-audited tables: every regulated table, each column classified as audited,
excluded, secret or personal. The table's own migration attaches the triggers
with the same label, pk and classes (cultures.audit.operations.attach_row_audit).
The invariants in tests/test_invariants.py compare this dict with pg_trigger and
with the real tables and columns, so the three cannot drift apart.

No personal value enters an append-only row (ADR 0005, update of 2026-10-18):
personal columns are stored as a marker, service events record that a personal
field changed, never its value, and a user actor is labelled by its public id.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EventType:
    code: str
    template: str  # how a timeline renders it
    reason_required: bool = False


EVENT_TYPES: dict[str, EventType] = {}


def register(event_type: EventType) -> EventType:
    if event_type.code in EVENT_TYPES:
        raise ValueError(f"audit event type {event_type.code!r} is registered twice")
    EVENT_TYPES[event_type.code] = event_type
    return event_type


def reason_required_codes() -> list[str]:
    return sorted(code for code, kind in EVENT_TYPES.items() if kind.reason_required)


USER_DEACTIVATED = register(
    EventType("user_deactivated", "{actor} deactivated {subject}", reason_required=True)
)
USERS_DEACTIVATED = register(
    EventType("users_deactivated", "{actor} deactivated {count} users", reason_required=True)
)
LAB_CREATED = register(EventType("lab_created", "{actor} created lab {subject}"))
LAB_UPDATED = register(EventType("lab_updated", "{actor} changed lab {subject}"))
MEMBER_ADDED = register(EventType("member_added", "{actor} added {user} as {role}"))
MEMBER_ROLE_CHANGED = register(
    EventType("member_role_changed", "{actor} changed the role of {user} to {role}")
)
MEMBER_REMOVED = register(EventType("member_removed", "{actor} removed {user}"))
USER_CREATED = register(EventType("user_created", "{actor} created {subject}"))
USER_CHANGED = register(EventType("user_changed", "{actor} changed {subject}"))
USER_ACTIVATED = register(
    EventType("user_activated", "{actor} activated {subject}", reason_required=True)
)
USER_STAFF_CHANGED = register(
    EventType(
        "user_staff_changed", "{actor} changed staff status of {subject}", reason_required=True
    )
)
USER_SUPERUSER_CHANGED = register(
    EventType(
        "user_superuser_changed",
        "{actor} changed superuser status of {subject}",
        reason_required=True,
    )
)
USER_PASSWORD_CHANGED = register(
    EventType("user_password_changed", "{actor} changed the password of {subject}")
)
# Recorded by the login limits (system actor) when failures from many addresses reach
# LOGIN_ACCOUNT_MAX_FAILURES: until the window ends only known browsers may sign in.
LOGIN_ACCOUNT_UNDER_ATTACK = register(
    EventType(
        "login_account_under_attack",
        "{subject} is under a password attack: only browsers used before may sign in",
    )
)
USER_LOGIN_LIMITS_CLEARED = register(
    EventType(
        "user_login_limits_cleared",
        "{actor} cleared the login limits of {subject}",
        reason_required=True,
    )
)


@dataclass(frozen=True)
class RowAudit:
    """How the row trigger treats one table. Every column is in exactly one class.

    label: the stable name stored on every RowChange, kept when the table is renamed.
    pk: the primary key columns, stored as text (a JSON array when there are several).
    exclude: noise, never stored, in no INSERT, UPDATE or DELETE row.
    secret: values never stored either, but an UPDATE that changes one records
    the column with the marker SECRET_MARKER as its old and new value, so a
    password change leaves a row without the hash (audit migration 0006).
    personal: values that name or reach a person (names, email, username). Every
    INSERT, UPDATE and DELETE row stores the marker PERSONAL_MARKER in their
    place, so the trail shows that the column was set or changed, and erasing a
    person never needs to touch an audit row (audit migration 0010, #37).
    audited: the other columns, listed so that a new column fails the
    classification invariant until someone decides which list it belongs to.
    """

    label: str
    audited: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    pk: tuple[str, ...] = ("id",)
    secret: tuple[str, ...] = ()
    personal: tuple[str, ...] = ()


# The value the row trigger stores for a changed secret column. Not a password (S105).
SECRET_MARKER = "redacted"  # noqa: S105
# The value the row trigger stores for a personal column, in every row that has the column.
PERSONAL_MARKER = "personal"


ROW_AUDITED_TABLES: dict[str, RowAudit] = {
    "users_user": RowAudit(
        label="users.user",
        # Ids, privilege flags and the join date say what happened to the account, not who
        # it is. They stay readable, and stay after an erasure.
        audited=(
            "id",
            "is_staff",
            "is_active",
            "is_superuser",
            "date_joined",
            "public_id",
        ),
        exclude=("last_login",),  # noise on every login
        secret=("password",),
        # The username is often a person's name or email address, so it is personal too.
        personal=("username", "first_name", "last_name", "email"),
    ),
    "labs_lab": RowAudit(
        label="labs.lab",
        # name and code name an organisational unit, not a person: the trail keeps their
        # values so old labels stay traceable. A lab is named after its field or unit;
        # a lab named after a person keeps that name in its history (ADR 0005, 2026-10-18).
        audited=("id", "public_id", "created_at", "updated_at", "name", "code"),
    ),
    "labs_membership": RowAudit(
        label="labs.membership",
        # Internal ids and a role: the person is reached only through users_user.
        audited=("id", "public_id", "created_at", "updated_at", "user_id", "lab_id", "role"),
    ),
}


# What a service event records for a personal field that was set or changed, never the value.
PERSONAL_CHANGED = "changed"
# The personal fields of each event subject type. record_event() and record_batch() write
# PERSONAL_CHANGED in their place, whatever the service passed (cultures.audit.events).
PERSONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "user": ROW_AUDITED_TABLES["users_user"].personal,
}


# Tables of the project's apps that the row trigger does not watch, each with the reason.
# tests/test_invariants.py walks every table of the project's models: each one is in
# ROW_AUDITED_TABLES or here, so a new table needs a decision before it ships.
NOT_ROW_AUDITED: dict[str, str] = {
    "audit_auditevent": "the service events themselves: append-only, never changed",
    "audit_rowchange": "the row changes themselves: written only by the row trigger",
    "users_user_groups": (
        "Django groups grant nothing here: rights come from lab roles (ADR 0006), and the "
        "user admin offers no groups"
    ),
    "users_user_user_permissions": (
        "per-user Django permissions are not used and the user admin offers none"
    ),
    "users_loginfailures": (
        "login failure counters: HMAC keys, windows and counts, no record of anyone. A row "
        "change per failed login would flood the trail. Staff clears are service events"
    ),
}
