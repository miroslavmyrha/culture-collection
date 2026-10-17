"""Registries of the audit trail: event types and the tables the row trigger watches.

This module imports no models, so models.py can build its constraints from it.

Event types: every code a service may record, with a timeline template. A code
registered twice raises at import. The types that need a reason are also a
check constraint on AuditEvent: adding one changes that constraint, and
`makemigrations --check` in check.sh fails until the migration exists. On a
large audit table write that migration as NOT VALID plus VALIDATE (RunSQL in
SeparateDatabaseAndState), because a plain AddConstraint scans the table under
an ACCESS EXCLUSIVE lock.

Row-audited tables: every regulated table, each column classified as audited
or excluded. The table's own migration attaches the triggers with the same
label, pk and exclusions (cultures.audit.operations.attach_row_audit). The
invariants in tests/test_invariants.py compare this dict with pg_trigger and
with the table's real columns, so the three cannot drift apart.
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


@dataclass(frozen=True)
class RowAudit:
    """How the row trigger treats one table. Every column is either audited or excluded.

    label: the stable name stored on every RowChange, kept when the table is renamed.
    pk: the primary key columns, stored as text (a JSON array when there are several).
    exclude: noise, never stored, in no INSERT, UPDATE or DELETE row.
    secret: values never stored either, but an UPDATE that changes one records
    the column with the marker SECRET_MARKER as its old and new value, so a
    password change leaves a row without the hash (audit migration 0006).
    audited: the other columns, listed so that a new column fails the
    classification invariant until someone decides which list it belongs to.
    """

    label: str
    audited: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    pk: tuple[str, ...] = ("id",)
    secret: tuple[str, ...] = ()


# The value the row trigger stores for a changed secret column. Not a password (S105).
SECRET_MARKER = "redacted"  # noqa: S105


ROW_AUDITED_TABLES: dict[str, RowAudit] = {
    "users_user": RowAudit(
        label="users.user",
        audited=(
            "id",
            "username",
            "first_name",
            "last_name",
            "email",
            "is_staff",
            "is_active",
            "is_superuser",
            "date_joined",
            "public_id",
        ),
        exclude=("last_login",),  # noise on every login
        secret=("password",),
    ),
    "labs_lab": RowAudit(
        label="labs.lab",
        audited=("id", "public_id", "created_at", "updated_at", "name", "code"),
    ),
    "labs_membership": RowAudit(
        label="labs.membership",
        audited=("id", "public_id", "created_at", "updated_at", "user_id", "lab_id", "role"),
    ),
}
