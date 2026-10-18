"""Both audit tables are append-only: the models, a trigger for every role, and the grants.

In development the app connects as the owner (a superuser in compose), so the
grants cannot hold there. Production runs the app as the runtime role of
ADR 0005, which owns nothing and gets exactly APP_ROLE_GRANTS
(cultures/audit/roles.py). These tests set up the same roles inside the test
transaction (the app_role fixture), switch to the runtime role with SET LOCAL
ROLE, and roll everything back afterwards. tests/test_roles.py covers the
setup itself.
"""

from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.backends.utils import CursorWrapper

from cultures.audit.context import AuditContext
from cultures.audit.models import AppendOnly, AuditEvent, RowChange
from cultures.users.models import User
from cultures.users.services import user_deactivate

from .conftest import TEST_ROLES, refused

pytestmark = pytest.mark.django_db

ROLE = TEST_ROLES.runtime
TABLES = ["audit_auditevent", "audit_rowchange"]


@pytest.fixture
def event(member: User, audited: AuditContext) -> AuditEvent:
    user_deactivate(user=member)
    return AuditEvent.objects.get()


@pytest.fixture
def row_change(event: AuditEvent) -> RowChange:
    return RowChange.objects.filter(op="UPDATE").get()


def snapshot() -> tuple[list[Any], list[Any]]:
    return (
        list(AuditEvent.objects.order_by("pk").values()),
        list(RowChange.objects.order_by("pk").values()),
    )


@pytest.fixture
def app_role(event: AuditEvent, runtime_role: CursorWrapper) -> CursorWrapper:
    """The runtime role, after a service wrote an event and a row change."""
    return runtime_role


def test_the_event_model_refuses_changes(event: AuditEvent) -> None:
    event.reason = "rewritten"
    with pytest.raises(AppendOnly):
        event.save()
    with pytest.raises(AppendOnly):
        event.delete()
    with pytest.raises(AppendOnly):
        AuditEvent.objects.update(reason="rewritten")
    with pytest.raises(AppendOnly):
        AuditEvent.objects.all().delete()


def test_the_row_change_model_refuses_writes(row_change: RowChange) -> None:
    row_change.op = "DELETE"
    with pytest.raises(AppendOnly):
        row_change.save()
    with pytest.raises(AppendOnly):
        RowChange(table_label="users.user", row_pk="1", op="INSERT", txid=1).save()
    with pytest.raises(AppendOnly):
        row_change.delete()
    with pytest.raises(AppendOnly):
        RowChange.objects.update(op="DELETE")
    with pytest.raises(AppendOnly):
        RowChange.objects.all().delete()


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "statement", ["UPDATE {table} SET request_id = 'forged'", "DELETE FROM {table}"]
)
def test_the_database_refuses_changes_from_any_role(
    row_change: RowChange, table: str, statement: str
) -> None:
    """The trigger binds every role, the owner and superusers included."""
    before = snapshot()
    with (
        pytest.raises(DatabaseError, match=f"{table} is append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(statement.format(table=table))
    assert snapshot() == before


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE {table} SET request_id = 'forged'",
        "DELETE FROM {table}",
        "TRUNCATE {table}",
    ],
)
def test_the_app_role_cannot_change_or_truncate(
    app_role: CursorWrapper, table: str, statement: str
) -> None:
    app_role.execute(f"SELECT count(*) FROM {table}")  # noqa: S608 (reading works)
    before = snapshot()
    refused(app_role, statement.format(table=table), f"permission denied for table {table}")
    assert snapshot() == before


def test_the_app_role_cannot_forge_a_row_change(app_role: CursorWrapper) -> None:
    refused(
        app_role,
        "INSERT INTO audit_rowchange (occurred_at, stmt_at, txid, table_label, row_pk, op,"
        " db_role, db_application) VALUES (now(), now(), 1, 'users.user', '1', 'DELETE', 'x', 'x')",
        "permission denied for table audit_rowchange",
    )


def test_the_trigger_still_writes_for_the_app_role(member: User, app_role: CursorWrapper) -> None:
    """SECURITY DEFINER: the role cannot insert row changes, its updates still leave one."""
    app_role.execute("UPDATE users_user SET first_name = 'Grace' WHERE id = %s", [member.pk])
    app_role.execute(
        "SELECT op, old ->> 'first_name', new ->> 'first_name', db_role FROM audit_rowchange"
        " WHERE row_pk = %s ORDER BY id DESC",
        [str(member.pk)],
    )
    assert app_role.fetchone() == ("UPDATE", "", "Grace", "cultures")


def test_the_app_role_cannot_disable_the_trigger(app_role: CursorWrapper) -> None:
    refused(
        app_role,
        "ALTER TABLE users_user DISABLE TRIGGER audit_row_change",
        "must be owner of table users_user",
    )


def test_no_other_role_may_attach_the_trigger_function(app_role: CursorWrapper) -> None:
    """CREATE TRIGGER needs EXECUTE on the function, and PUBLIC lost it in the migration."""
    app_role.execute("SELECT has_function_privilege('audit_row_change()', 'EXECUTE')")
    assert app_role.fetchone() == (False,)


def test_the_app_role_cannot_truncate_a_regulated_table(app_role: CursorWrapper) -> None:
    """The TRUNCATE trigger would record it; without the grant it cannot happen at all."""
    refused(app_role, "TRUNCATE users_user CASCADE", "permission denied for table users_user")


@pytest.mark.parametrize("table", TABLES)
def test_a_role_granted_truncate_by_mistake_is_still_refused(
    app_role: CursorWrapper, table: str
) -> None:
    """The guard refuses TRUNCATE for every role that does not own the table."""
    app_role.execute("RESET ROLE")
    app_role.execute("SET CONSTRAINTS ALL IMMEDIATE")  # no pending FK checks block TRUNCATE
    app_role.execute(f"GRANT TRUNCATE ON {table} TO {ROLE}")
    app_role.execute(f"SET LOCAL ROLE {ROLE}")
    before = snapshot()
    refused(app_role, f"TRUNCATE {table}", f"{table} is append-only: TRUNCATE by {ROLE} refused")
    app_role.execute("RESET ROLE")
    assert snapshot() == before
