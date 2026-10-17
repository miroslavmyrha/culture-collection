"""audit 0006 and users 0003 (the secret marker) go back and forth.

Both are raw SQL: the function body and the trigger arguments are checked in
pg_proc and pg_trigger after each direction, and a password change shows the
behaviour of each state.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from cultures.users.models import User

from .test_invariants import installed_row_triggers

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow, pytest.mark.migrations]
BEFORE = [("audit", "0005_auditevent_lab_time_idx"), ("users", "0002_row_audit")]


def migrate(targets: list[tuple[str, str]] | None = None) -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(targets or executor.loader.graph.leaf_nodes())


@pytest.fixture
def back_to_the_leaf() -> Iterator[None]:
    yield
    migrate()  # later tests need the current schema, whatever happened here


def query(sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        found: list[tuple[Any, ...]] = cursor.fetchall() if cursor.description else []
        return found


def password_change_rows(user: User, password: str) -> list[tuple[Any, ...]]:
    """The UPDATE rows a raw password change leaves for this user."""
    query("UPDATE users_user SET password = %s WHERE id = %s", [password, user.pk])
    return query(
        "SELECT old ->> 'password', new ->> 'password' FROM audit_rowchange"
        " WHERE table_label = 'users.user' AND row_pk = %s AND op = 'UPDATE' ORDER BY id",
        [str(user.pk)],
    )


def function_body() -> str:
    ((body,),) = query("SELECT prosrc FROM pg_proc WHERE proname = 'audit_row_change'")
    return str(body)


@pytest.mark.usefixtures("back_to_the_leaf")
def test_the_secret_marker_migrations_go_back_and_forth() -> None:
    user = User.objects.create_user("migrating")
    assert password_change_rows(user, "hash-1") == [("redacted", "redacted")]

    migrate(BEFORE)
    assert "secret:" not in function_body()
    update_args = installed_row_triggers()["users_user"]["audit_row_update"][3]
    assert update_args == ("users.user", '["id"]', "password", "last_login")
    assert password_change_rows(user, "hash-2") == [("redacted", "redacted")]  # no new row

    migrate()
    assert "secret:" in function_body()
    update_args = installed_row_triggers()["users_user"]["audit_row_update"][3]
    assert update_args == ("users.user", '["id"]', "last_login", "secret:password")
    assert password_change_rows(user, "hash-3") == [("redacted", "redacted")] * 2
