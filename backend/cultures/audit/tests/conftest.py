"""Fixtures named after who acts: an admin who deactivates, the members it acts on,
and the production database roles (ADR 0005)."""

from collections.abc import Iterator

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.backends.utils import CursorWrapper
from model_bakery import baker

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import Channel
from cultures.audit.roles import Roles, setup
from cultures.users.models import User


def make_user(username: str) -> User:
    user: User = baker.make(User, username=username, email=f"{username}@example.org")
    return user


@pytest.fixture
def admin() -> User:
    """The person who changes other users."""
    return make_user("admin")


@pytest.fixture
def member() -> User:
    return make_user("member")


@pytest.fixture
def audited(admin: User) -> Iterator[AuditContext]:
    """Service tests run outside a request: a command run by the admin, with a reason."""
    with audit_context(
        channel=Channel.COMMAND, actor=admin, reason="left the lab", request_id="cmd-1"
    ) as context:
        yield context


# The production roles under names of their own: role names are cluster-wide, and the
# development cluster may hold the real ones (tools/up-with-runtime-role.sh).
TEST_ROLES = Roles(
    audit_owner="cultures_test_audit",
    migration="cultures_test_migration",
    runtime="cultures_test_runtime",
)


@pytest.fixture
def database_roles() -> Iterator[CursorWrapper]:
    """The roles set up exactly as `manage.py db_roles` does, inside a savepoint.

    The savepoint is always rolled back: that drops the roles, the owner changes and
    any SET LOCAL ROLE, so teardown runs as the owner again. A statement expected to
    fail runs in its own atomic() (refused()), or the savepoint is left aborted.
    """
    with transaction.atomic(), connection.cursor() as cursor:
        # ALTER TABLE ... OWNER refuses a table with pending FK checks (Django's are deferred).
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        setup(cursor, TEST_ROLES)
        yield cursor
        transaction.set_rollback(True)


@pytest.fixture
def runtime_role(database_roles: CursorWrapper) -> CursorWrapper:
    """A cursor (and the ORM on the same connection) acting as the runtime role."""
    database_roles.execute(f"SET LOCAL ROLE {TEST_ROLES.runtime}")
    return database_roles


def refused(cursor: CursorWrapper, sql: str, match: str) -> None:
    with pytest.raises(DatabaseError, match=match), transaction.atomic():
        cursor.execute(sql)
