"""The database roles of ADR 0005 (cultures/audit/roles.py), set up inside the test transaction.

What must hold: the runtime role can do the app's work and nothing that empties,
edits or switches off the audit trail. The audit owner owns the audit tables and
functions after setup and after every migrate. The setup can run twice. And the
privileges in the database are exactly APP_ROLE_GRANTS, checked here with
has_table_privilege, not with the code that grants them.
"""

from io import StringIO
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.sql import emit_post_migrate_signal
from django.db import connection, transaction
from django.db.backends.utils import CursorWrapper
from pytest_django.fixtures import Settings

from cultures.audit import roles as roles_module
from cultures.audit.context import AuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.audit.registry import ROW_AUDITED_TABLES
from cultures.audit.roles import (
    APP_ROLE_GRANTS,
    DOMAIN_TABLE,
    Roles,
    audit_tables,
    setup,
)
from cultures.labs import services as labs
from cultures.labs.permissions import Role
from cultures.users.models import User

from .conftest import TEST_ROLES, refused

pytestmark = pytest.mark.django_db

# Every privilege PostgreSQL 18 knows for a table (MAINTAIN is new in 17).
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)
AUDIT_FUNCTIONS = (
    "audit_refuse_change",
    "audit_refuse_truncate",
    "audit_row_change",
    "audit_row_truncate",
)


def fetch(
    cursor: CursorWrapper, sql: str, params: list[Any] | None = None
) -> list[tuple[Any, ...]]:
    cursor.execute(sql, params)
    rows: list[tuple[Any, ...]] = cursor.fetchall()
    return rows


def public_tables(cursor: CursorWrapper) -> list[str]:
    return [
        name
        for (name,) in fetch(
            cursor,
            "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
            " AND relkind IN ('r', 'p') ORDER BY relname",
        )
    ]


def owners(cursor: CursorWrapper) -> dict[str, str]:
    """Owner of every relation (tables, sequences, indexes) and audit function in public."""
    return dict(
        fetch(
            cursor,
            "SELECT relname, pg_get_userbyid(relowner) FROM pg_class"
            " WHERE relnamespace = 'public'::regnamespace"
            " UNION ALL SELECT proname || '()', pg_get_userbyid(proowner) FROM pg_proc"
            " WHERE pronamespace = 'public'::regnamespace",
        )
    )


def state(cursor: CursorWrapper) -> list[Any]:
    """Everything setup() changes: owners, ACLs, default ACLs, memberships, schema ACL."""
    roles = list(TEST_ROLES.__dict__.values())
    return [
        sorted(owners(cursor).items()),
        fetch(
            cursor,
            "SELECT relname, relacl::text FROM pg_class"
            " WHERE relnamespace = 'public'::regnamespace ORDER BY relname",
        ),
        fetch(
            cursor,
            "SELECT defaclrole::regrole::text, defaclacl::text FROM pg_default_acl ORDER BY 1",
        ),
        fetch(
            cursor,
            "SELECT roleid::regrole::text, member::regrole::text, grantor::regrole::text,"
            " admin_option, inherit_option, set_option FROM pg_auth_members"
            " WHERE member::regrole::text = ANY(%s) OR roleid::regrole::text = ANY(%s)"
            " ORDER BY 1, 2, 3",
            [roles, roles],
        ),
        fetch(cursor, "SELECT nspacl::text FROM pg_namespace WHERE nspname = 'public'"),
    ]


def test_the_runtime_privileges_are_exactly_app_role_grants(database_roles: CursorWrapper) -> None:
    """The self-test of the single source: every table, every privilege, as the database sees it."""
    tables = public_tables(database_roles)
    assert {"audit_auditevent", "audit_rowchange", "users_user", "labs_lab"} <= set(tables)
    actual = {
        table: tuple(
            privilege
            for privilege in TABLE_PRIVILEGES
            if fetch(
                database_roles,
                "SELECT has_table_privilege(%s, %s, %s)",
                [TEST_ROLES.runtime, f"public.{table}", privilege],
            )
            == [(True,)]
        )
        for table in tables
    }
    expected = {table: APP_ROLE_GRANTS.get(table, DOMAIN_TABLE) for table in tables}
    assert actual == expected
    assert actual["audit_auditevent"] == ("SELECT", "INSERT")
    assert actual["audit_rowchange"] == ("SELECT",)
    assert actual["users_user"] == ("SELECT", "INSERT", "UPDATE", "DELETE")


def test_the_runtime_role_has_no_sequence_privilege(database_roles: CursorWrapper) -> None:
    """Identity columns take their ids without one."""
    sequences = fetch(
        database_roles,
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
        " AND relkind = 'S' AND (has_sequence_privilege(%s, oid, 'USAGE')"
        " OR has_sequence_privilege(%s, oid, 'SELECT')"
        " OR has_sequence_privilege(%s, oid, 'UPDATE'))",
        [TEST_ROLES.runtime] * 3,
    )
    assert sequences == []


def test_the_trigger_functions_cannot_be_executed_by_the_runtime_role(
    database_roles: CursorWrapper,
) -> None:
    for function in AUDIT_FUNCTIONS:
        assert fetch(
            database_roles,
            "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
            [TEST_ROLES.runtime, f"public.{function}()"],
        ) == [(False,)], function


def test_the_audit_owner_owns_the_audit_tables_and_functions(database_roles: CursorWrapper) -> None:
    owned = owners(database_roles)
    for name in ("audit_auditevent", "audit_rowchange", "audit_rowchange_id_seq"):
        assert owned[name] == TEST_ROLES.audit_owner, name
    for function in AUDIT_FUNCTIONS:
        assert owned[f"{function}()"] == TEST_ROLES.audit_owner, function


def test_every_other_table_belongs_to_the_migration_role_and_the_runtime_role_owns_nothing(
    database_roles: CursorWrapper,
) -> None:
    owned = owners(database_roles)
    for table in public_tables(database_roles):
        expected = TEST_ROLES.audit_owner if table in audit_tables() else TEST_ROLES.migration
        assert owned[table] == expected, table
    assert TEST_ROLES.runtime not in owned.values()


def test_the_roles_have_the_right_attributes(database_roles: CursorWrapper) -> None:
    rows = fetch(
        database_roles,
        "SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls"
        " FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
        [list(TEST_ROLES.__dict__.values())],
    )
    assert rows == [
        (TEST_ROLES.audit_owner, False, False, False, False, False),
        (TEST_ROLES.migration, True, False, False, False, False),
        (TEST_ROLES.runtime, True, False, False, False, False),
    ]
    # The runtime role is a member of nothing, the migration role inherits the audit owner.
    assert fetch(
        database_roles,
        "SELECT roleid::regrole::text, member::regrole::text, inherit_option FROM pg_auth_members"
        " WHERE member::regrole::text = ANY(%s)",
        [[TEST_ROLES.runtime, TEST_ROLES.migration]],
    ) == [(TEST_ROLES.audit_owner, TEST_ROLES.migration, True)]


def test_setup_applies_the_same_state_twice(database_roles: CursorWrapper) -> None:
    first = state(database_roles)
    setup(database_roles, TEST_ROLES)
    assert state(database_roles) == first


def test_the_command_sets_up_the_configured_roles(settings: Settings) -> None:
    settings.DATABASE_ROLES = TEST_ROLES.__dict__
    out = StringIO()
    with transaction.atomic():
        call_command("db_roles", stdout=out)
        with connection.cursor() as cursor:
            assert owners(cursor)["audit_rowchange"] == TEST_ROLES.audit_owner
            assert owners(cursor)["users_user"] == TEST_ROLES.migration
        transaction.set_rollback(True)
    assert "Database roles ready" in out.getvalue()


def test_tables_created_by_the_migration_role_reach_the_runtime_role(
    database_roles: CursorWrapper,
) -> None:
    """Default privileges: createcachetable runs after migrate, with no post_migrate step."""
    database_roles.execute(f"SET LOCAL ROLE {TEST_ROLES.migration}")
    database_roles.execute("CREATE TABLE public.probe_cache (cache_key text PRIMARY KEY)")
    database_roles.execute(f"SET LOCAL ROLE {TEST_ROLES.runtime}")
    database_roles.execute("INSERT INTO probe_cache VALUES ('k')")
    database_roles.execute("DELETE FROM probe_cache")
    refused(database_roles, "TRUNCATE probe_cache", "permission denied for table probe_cache")


def test_setup_refuses_a_privileged_runtime_role(settings: Settings) -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {TEST_ROLES.runtime} LOGIN CREATEROLE")
        with pytest.raises(ImproperlyConfigured, match="plain login role"):
            setup(cursor, TEST_ROLES)
        transaction.set_rollback(True)


def test_setup_refuses_a_runtime_role_that_is_a_member_of_another_role() -> None:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {TEST_ROLES.runtime} LOGIN IN ROLE pg_read_all_data")
        with pytest.raises(ImproperlyConfigured, match="member of no role"):
            setup(cursor, TEST_ROLES)
        transaction.set_rollback(True)


@pytest.mark.parametrize(
    "names",
    [
        ("audit", "migration", "app; DROP TABLE users_user"),
        ("same", "same", "app"),
        ("Audit", "migration", "app"),
    ],
)
def test_role_names_must_be_plain_and_distinct(names: tuple[str, str, str]) -> None:
    with pytest.raises(ImproperlyConfigured):
        Roles(*names)


def test_every_audit_table_needs_its_own_grant_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new audit table must not fall back to the domain privileges (UPDATE, DELETE)."""
    assert audit_tables() == ["audit_auditevent", "audit_rowchange"]
    monkeypatch.delitem(roles_module.APP_ROLE_GRANTS, "audit_rowchange")
    with pytest.raises(ImproperlyConfigured, match="audit_rowchange"):
        audit_tables()


# After migrate


def drift(cursor: CursorWrapper) -> None:
    """What a migration as the migration role leaves: a new audit function it owns, an
    audit table back in its hands, and a default privilege the runtime role must not keep."""
    cursor.execute("RESET ROLE")
    cursor.execute(f"ALTER TABLE audit_rowchange OWNER TO {TEST_ROLES.migration}")
    cursor.execute(f"GRANT UPDATE, DELETE ON audit_rowchange TO {TEST_ROLES.runtime}")
    cursor.execute(f"SET LOCAL ROLE {TEST_ROLES.migration}")
    cursor.execute("CREATE FUNCTION public.audit_probe() RETURNS int LANGUAGE sql AS 'SELECT 1'")


def test_migrate_as_the_migration_role_restores_owners_and_grants(
    database_roles: CursorWrapper, settings: Settings
) -> None:
    settings.DATABASE_ROLES = TEST_ROLES.__dict__
    drift(database_roles)
    out = StringIO()
    emit_post_migrate_signal(1, False, "default", stdout=out)  # what migrate sends at its end
    owned = owners(database_roles)
    assert owned["audit_rowchange"] == TEST_ROLES.audit_owner
    assert owned["audit_probe()"] == TEST_ROLES.audit_owner
    assert fetch(
        database_roles,
        "SELECT has_table_privilege(%s, 'audit_rowchange', 'UPDATE, DELETE')",
        [TEST_ROLES.runtime],
    ) == [(False,)]
    assert f"audit objects owned by {TEST_ROLES.audit_owner}" in out.getvalue()


def test_migrate_as_another_role_changes_nothing_and_says_so(
    database_roles: CursorWrapper, settings: Settings
) -> None:
    settings.DATABASE_ROLES = TEST_ROLES.__dict__
    drift(database_roles)
    database_roles.execute("RESET ROLE")  # the owner, as in development
    before = state(database_roles)
    out = StringIO()
    emit_post_migrate_signal(1, False, "default", stdout=out)
    assert state(database_roles) == before
    assert f"not {TEST_ROLES.migration}: privileges unchanged" in out.getvalue()


def test_apply_refuses_a_table_the_roles_do_not_own(database_roles: CursorWrapper) -> None:
    database_roles.execute("RESET ROLE")
    database_roles.execute("CREATE TABLE public.probe_foreign (id int)")  # owned by the login
    with pytest.raises(ImproperlyConfigured, match="probe_foreign"):
        roles_module.apply_grants(database_roles, TEST_ROLES)


# What the runtime role cannot do


AUDIT_REFUSALS = [
    ("TRUNCATE {table}", "permission denied for table {table}"),
    ("UPDATE {table} SET request_id = 'x'", "permission denied for table {table}"),
    ("DELETE FROM {table}", "permission denied for table {table}"),
    ("ALTER TABLE {table} ADD COLUMN probe int", "must be owner of table {table}"),
    ("ALTER TABLE {table} DISABLE TRIGGER audit_append_only", "must be owner of table {table}"),
    ("DROP TRIGGER audit_append_only ON {table}", "must be owner of relation {table}"),
    ("DROP TABLE {table}", "must be owner of table {table}"),
]


@pytest.mark.parametrize("table", ["audit_auditevent", "audit_rowchange"])
@pytest.mark.parametrize(("statement", "message"), AUDIT_REFUSALS)
def test_the_runtime_role_cannot_change_an_audit_table(
    runtime_role: CursorWrapper, table: str, statement: str, message: str
) -> None:
    refused(runtime_role, statement.format(table=table), message.format(table=table))


def test_the_runtime_role_cannot_insert_a_row_change(runtime_role: CursorWrapper) -> None:
    refused(
        runtime_role,
        "INSERT INTO audit_rowchange (stmt_at, txid, table_label, row_pk, op, db_role,"
        " db_application) VALUES (now(), 1, 'users.user', '1', 'DELETE', 'x', 'x')",
        "permission denied for table audit_rowchange",
    )


REGULATED_REFUSALS = [
    ("TRUNCATE {table} CASCADE", "permission denied for table {table}"),
    ("TRUNCATE {table}", "permission denied for table {table}"),
    ("ALTER TABLE {table} DISABLE TRIGGER audit_row_change", "must be owner of table {table}"),
    ("ALTER TABLE {table} DISABLE TRIGGER ALL", "must be owner of table {table}"),
    ("DROP TRIGGER audit_row_update ON {table}", "must be owner of relation {table}"),
    ("ALTER TABLE {table} OWNER TO CURRENT_USER", "must be owner of table {table}"),
]


@pytest.mark.parametrize("table", sorted(ROW_AUDITED_TABLES))
@pytest.mark.parametrize(("statement", "message"), REGULATED_REFUSALS)
def test_the_runtime_role_cannot_empty_or_unhook_a_regulated_table(
    runtime_role: CursorWrapper, table: str, statement: str, message: str
) -> None:
    refused(runtime_role, statement.format(table=table), message.format(table=table))


def test_a_cascade_from_a_regulated_table_leaves_the_events(
    runtime_role: CursorWrapper, audited: AuditContext, admin: User
) -> None:
    """The review's case: TRUNCATE users_user CASCADE as the owner emptied audit_auditevent."""
    labs.lab_create(name="Cascade", code="CSC")
    events = AuditEvent.objects.count()
    assert events > 0
    runtime_role.execute("SET CONSTRAINTS ALL IMMEDIATE")  # no pending FK check blocks TRUNCATE
    refused(runtime_role, "TRUNCATE users_user CASCADE", "permission denied for table users_user")
    assert AuditEvent.objects.count() == events


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("SET session_replication_role = replica", "permission denied to set parameter"),
        ("CREATE TABLE public.probe (id int)", "permission denied for schema public"),
        ("CREATE ROLE probe", "permission denied to create role"),
    ],
)
def test_the_runtime_role_cannot_switch_triggers_off_or_create_objects(
    runtime_role: CursorWrapper, statement: str, message: str
) -> None:
    refused(runtime_role, statement, message)


# What the runtime role does every day


def test_the_app_writes_as_the_runtime_role_and_both_layers_record_them(
    runtime_role: CursorWrapper, audited: AuditContext, admin: User
) -> None:
    lab = labs.lab_create(name="Runtime", code="RUN")
    member = User.objects.create(username="runtime-member", email="rm@example.org")
    membership = labs.membership_create(lab=lab, user=member, role=Role.VIEWER)
    labs.membership_set_role(membership=membership, role=Role.CURATOR)
    labs.membership_delete(membership=membership)

    assert fetch(runtime_role, "SELECT current_user") == [(TEST_ROLES.runtime,)]
    events = AuditEvent.objects.filter(request_id="cmd-1")
    assert set(events.values_list("event_type", flat=True)) >= {
        "lab_created",
        "member_added",
        "member_role_changed",
        "member_removed",
    }
    assert {event.actor_id for event in events} == {admin.pk}
    changes = RowChange.objects.filter(request_id="cmd-1", table_label="labs.membership")
    assert [change.op for change in changes.order_by("pk")] == ["INSERT", "UPDATE", "DELETE"]
    assert {change.actor_id for change in changes} == {admin.pk}
    assert {change.txid for change in changes} <= set(events.values_list("txid", flat=True))


def test_the_runtime_role_keeps_sessions(runtime_role: CursorWrapper) -> None:
    from django.contrib.sessions.backends.db import SessionStore  # noqa: PLC0415

    session = SessionStore()
    session["probe"] = 1
    session.save()
    assert SessionStore(session_key=session.session_key)["probe"] == 1
    session.delete()
