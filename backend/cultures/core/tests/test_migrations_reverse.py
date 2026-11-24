"""Every migration of the project goes back (#42): a failed deploy can step the schema back, and
a migration test can start from any earlier state.

The static test reads each operation: a RunPython without reverse_code or a RunSQL without
reverse_sql cannot go back. The round trip takes every app of the project to zero and forward
again on the test database, which is what the reverse code and SQL actually do.
"""

from collections.abc import Iterator, Sequence

import pytest
from django.apps import apps
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.base import Operation

from cultures.audit.tests.test_migration_secret_marker import migrate, query

PROJECT = sorted(c.label for c in apps.get_app_configs() if c.name.startswith("cultures."))


def irreversible(operations: Sequence[Operation]) -> list[str]:
    """The operations that cannot go back, nested ones of SeparateDatabaseAndState included."""
    found: list[str] = []
    for operation in operations:
        nested = getattr(operation, "database_operations", None)
        if nested is not None:
            found += irreversible(nested)
        elif not operation.reversible:
            found.append(operation.describe())
    return found


def test_every_migration_of_the_project_can_go_back() -> None:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    stuck = [
        f"{app}.{name}: {what}"
        for (app, name), migration in sorted(loader.disk_migrations.items())
        if app in PROJECT
        for what in irreversible(migration.operations)
    ]
    assert stuck == []


def test_an_operation_without_its_reverse_is_found() -> None:
    forward_only = migrations.RunSQL("SELECT 1")
    wrapped = migrations.SeparateDatabaseAndState(database_operations=[forward_only])
    assert irreversible([migrations.RunSQL("SELECT 1", "SELECT 1"), wrapped]) == [
        forward_only.describe()
    ]


@pytest.fixture
def back_to_the_leaf() -> Iterator[None]:
    yield
    migrate()  # later tests need the current schema, whatever happened here


@pytest.mark.django_db(transaction=True)
@pytest.mark.slow
@pytest.mark.migrations
@pytest.mark.usefixtures("back_to_the_leaf")
def test_the_whole_schema_goes_to_zero_and_back() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate([(app, None) for app in PROJECT])
    tables = {t for (t,) in query("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert not any(t.startswith(tuple(f"{app}_" for app in PROJECT)) for t in tables)
    migrate()
    tables = {t for (t,) in query("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"labs_lab", "audit_auditevent", "strains_strain"} <= tables
