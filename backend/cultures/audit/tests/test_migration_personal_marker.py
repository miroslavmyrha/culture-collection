"""audit 0010 and users 0006 (the personal marker of #37) go back and forth.

Both are raw SQL: the function body and the trigger arguments are checked in
pg_proc and pg_trigger after each direction, and a raw rename shows the
behaviour of each state. The claims and secret lines of 0008 must survive.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from cultures.users.models import User

from .test_invariants import installed_row_triggers
from .test_migration_secret_marker import function_body, migrate, query

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow, pytest.mark.migrations]
BEFORE = [("audit", "0009_reason_required_login_limits_cleared"), ("users", "0005_login_failures")]
PERSONAL_ARGS = ("personal:username", "personal:first_name", "personal:last_name", "personal:email")


@pytest.fixture
def back_to_the_leaf() -> Iterator[None]:
    yield
    migrate()  # later tests need the current schema, whatever happened here


def rename_rows(user: User, name: str) -> list[tuple[Any, ...]]:
    """The UPDATE rows a raw rename leaves for this user, with the stored first_name values."""
    query("UPDATE users_user SET first_name = %s WHERE id = %s", [name, user.pk])
    return query(
        "SELECT old ->> 'first_name', new ->> 'first_name' FROM audit_rowchange"
        " WHERE table_label = 'users.user' AND row_pk = %s AND op = 'UPDATE' ORDER BY id",
        [str(user.pk)],
    )


@pytest.mark.usefixtures("back_to_the_leaf")
def test_the_personal_marker_migrations_go_back_and_forth() -> None:
    user = User.objects.create_user("migrating")
    assert rename_rows(user, "Ada") == [("personal", "personal")]

    migrate(BEFORE)
    body = function_body()
    assert "personal:" not in body
    assert "actor_claim_invalid" in body  # back to 0008, not to an older body
    assert "secret:" in body
    update_args = installed_row_triggers()["users_user"]["audit_row_update"][3]
    assert update_args == ("users.user", '["id"]', "last_login", "secret:password")
    assert rename_rows(user, "Grace")[-1] == ("Ada", "Grace")  # values again

    migrate()
    body = function_body()
    assert "personal:" in body
    assert "actor_claim_invalid" in body
    assert "secret:" in body
    update_args = installed_row_triggers()["users_user"]["audit_row_update"][3]
    assert update_args == ("users.user", '["id"]', "last_login", "secret:password", *PERSONAL_ARGS)
    assert rename_rows(user, "Hedy")[-1] == ("personal", "personal")
