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


@dataclass(frozen=True)
class RowAudit:
    """How the row trigger treats one table. Every column is either audited or excluded.

    label: the stable name stored on every RowChange, kept when the table is renamed.
    pk: the primary key columns, stored as text (a JSON array when there are several).
    exclude: secrets and noise, never stored, in no INSERT, UPDATE or DELETE row.
    audited: the other columns, listed so that a new column fails the
    classification invariant until someone decides which list it belongs to.
    """

    label: str
    audited: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    pk: tuple[str, ...] = ("id",)


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
        exclude=("password", "last_login"),  # a secret, and noise on every login
    ),
}
