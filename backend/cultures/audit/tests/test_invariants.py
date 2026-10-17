"""Every regulated table has its row triggers, enabled, and every column classified.

The walks read pg_trigger and information_schema, so these all fail here:
a table registered without its migration, a migration that drifted from the
registry, a trigger attached by hand, a trigger switched off with DISABLE
TRIGGER, and a new column nobody classified as audited or excluded.
"""

import pytest
from django.db import connection

from cultures.audit.operations import ROW_TRIGGERS, row_trigger_args
from cultures.audit.registry import ROW_AUDITED_TABLES, RowAudit

pytestmark = pytest.mark.django_db

# (tgenabled, tgtype, WHEN condition, arguments) per trigger.
Trigger = tuple[str, int, str | None, tuple[str, ...]]
Installed = dict[str, dict[str, Trigger]]

# tgtype bits (src/include/catalog/pg_trigger.h): ROW 1, BEFORE 2, INSERT 4, DELETE 8,
# UPDATE 16, TRUNCATE 32. AFTER is the absence of BEFORE.
AFTER_ROW_INSERT_DELETE, AFTER_ROW_UPDATE, AFTER_STATEMENT_TRUNCATE = 13, 17, 32
CHANGED_ROWS_ONLY = "(old.* IS DISTINCT FROM new.*)"


def installed_row_triggers() -> Installed:
    """{table: {trigger: Trigger}} for every row audit trigger in the database."""
    with connection.cursor() as cursor:
        cursor.execute(
            r"""
            SELECT c.relname, t.tgname, t.tgenabled, t.tgtype,
                   substring(pg_get_triggerdef(t.oid) from 'WHEN \((.*)\) EXECUTE'), t.tgargs
              FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
             WHERE t.tgname = ANY(%s) AND NOT t.tgisinternal
            """,
            [list(ROW_TRIGGERS)],
        )
        found = cursor.fetchall()
    installed: Installed = {}
    for table, trigger, enabled, kind, when, args in found:
        # tgargs is bytea: every argument ends with a NUL byte.
        arguments = tuple(bytes(args).decode().split("\x00")[:-1])
        installed.setdefault(table, {})[trigger] = (enabled, kind, when, arguments)
    return installed


def expected_triggers(audit: RowAudit) -> dict[str, Trigger]:
    """ "O": fires in the normal (origin) replication mode, the enabled state."""
    args = row_trigger_args(audit.label, audit.pk, audit.exclude)
    return {
        "audit_row_change": ("O", AFTER_ROW_INSERT_DELETE, None, args),
        "audit_row_update": ("O", AFTER_ROW_UPDATE, CHANGED_ROWS_ONLY, args),
        "audit_row_truncate": ("O", AFTER_STATEMENT_TRUNCATE, None, (audit.label,)),
    }


def row_audit_mismatches() -> list[str]:
    """Registered tables without their enabled triggers, and triggers nobody registered."""
    installed = installed_row_triggers()
    wrong = [
        f"{table}: expected {expected_triggers(audit)}, found {installed.get(table)}"
        for table, audit in sorted(ROW_AUDITED_TABLES.items())
        if installed.get(table) != expected_triggers(audit)
    ]
    wrong.extend(
        f"{table}: row audit triggers installed but not in ROW_AUDITED_TABLES"
        for table in sorted(set(installed) - set(ROW_AUDITED_TABLES))
    )
    return wrong


def unclassified_columns() -> list[str]:
    """Columns of registered tables that are neither audited nor excluded, or both, or gone."""
    wrong: list[str] = []
    with connection.cursor() as cursor:
        for table, audit in sorted(ROW_AUDITED_TABLES.items()):
            cursor.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = current_schema() AND table_name = %s",
                [table],
            )
            columns = {name for (name,) in cursor.fetchall()}
            audited, excluded = set(audit.audited), set(audit.exclude)
            wrong.extend(
                f"{table}.{c}: not classified" for c in sorted(columns - audited - excluded)
            )
            wrong.extend(
                f"{table}.{c}: no such column" for c in sorted((audited | excluded) - columns)
            )
            wrong.extend(f"{table}.{c}: audited and excluded" for c in sorted(audited & excluded))
            wrong.extend(f"{table}.{c}: pk not audited" for c in audit.pk if c not in audited)
    return wrong


def test_every_registered_table_has_its_row_triggers() -> None:
    assert ROW_AUDITED_TABLES  # an empty registry must not pass
    assert set(installed_row_triggers()["users_user"]) == set(ROW_TRIGGERS)  # real triggers read
    assert row_audit_mismatches() == []


def test_every_column_of_a_registered_table_is_audited_or_excluded() -> None:
    assert ROW_AUDITED_TABLES
    assert unclassified_columns() == []


# The invariants themselves: each fault they exist to catch makes them fail.


def test_a_registered_table_without_the_triggers_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = RowAudit(label="audit.auditevent", audited=())
    monkeypatch.setitem(ROW_AUDITED_TABLES, "audit_auditevent", audit)
    assert row_audit_mismatches() == [
        f"audit_auditevent: expected {expected_triggers(audit)}, found None",
    ]


def test_an_exclusion_that_drifted_from_the_migration_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = RowAudit(label="users.user", audited=(), exclude=("password",))
    monkeypatch.setitem(ROW_AUDITED_TABLES, "users_user", drifted)
    assert [line.split(":")[0] for line in row_audit_mismatches()] == ["users_user"]


def test_a_disabled_trigger_is_found() -> None:
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE users_user DISABLE TRIGGER audit_row_update")
    assert installed_row_triggers()["users_user"]["audit_row_update"][0] == "D"
    assert [line.split(":")[0] for line in row_audit_mismatches()] == ["users_user"]


def test_an_unregistered_trigger_is_found() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TRIGGER audit_row_change AFTER INSERT ON django_session FOR EACH ROW"
            " EXECUTE FUNCTION audit_row_change('sessions.session', '[\"session_key\"]')"
        )
    assert row_audit_mismatches() == [
        "django_session: row audit triggers installed but not in ROW_AUDITED_TABLES",
    ]


def test_a_new_column_nobody_classified_is_found() -> None:
    with connection.cursor() as cursor:
        cursor.execute("ALTER TABLE users_user ADD COLUMN national_id text")
    assert unclassified_columns() == ["users_user.national_id: not classified"]


def test_a_wrong_classification_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = ROW_AUDITED_TABLES["users_user"]
    wrong = RowAudit(
        label=audit.label,
        audited=(*audit.audited[1:], "password", "nickname"),
        exclude=audit.exclude,
    )
    monkeypatch.setitem(ROW_AUDITED_TABLES, "users_user", wrong)
    assert unclassified_columns() == [
        "users_user.id: not classified",
        "users_user.nickname: no such column",
        "users_user.password: audited and excluded",
        "users_user.id: pk not audited",
    ]


@pytest.mark.parametrize(
    "definition",
    [
        "AFTER UPDATE ON users_user FOR EACH ROW",  # no WHEN: the function runs for no-op saves
        "AFTER UPDATE ON users_user FOR EACH STATEMENT",
        "BEFORE UPDATE ON users_user FOR EACH ROW WHEN (OLD IS DISTINCT FROM NEW)",
    ],
)
def test_an_update_trigger_of_the_wrong_shape_is_found(definition: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP TRIGGER audit_row_update ON users_user")
        cursor.execute(
            f"CREATE TRIGGER audit_row_update {definition} EXECUTE FUNCTION"
            " audit_row_change('users.user', '[\"id\"]', 'password', 'last_login')"
        )
    assert [line.split(":")[0] for line in row_audit_mismatches()] == ["users_user"]
