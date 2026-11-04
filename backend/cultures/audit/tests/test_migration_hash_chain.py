"""audit 0034 (the hash chain of ADR 0009) goes back and forth over rows that already exist.

What a database that already holds audit rows gets: the migration chains those
rows too, with the append-only trigger switched off for its own length, so after
it every row is in the chain and `chain.walk` is intact. The hashes are computed
from the rows' current content, so they prove nothing about what happened to
them before the migration ran. That is why ADR 0009 asks for the chain before the
first production data; here only development, seed and test databases hold rows.

The rows are written with raw SQL, because between the two states the models
carry three columns the table does not.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection

from cultures.audit import chain
from cultures.users.models import User

from .test_migration_secret_marker import migrate, query

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow, pytest.mark.migrations]
BEFORE = [("audit", "0033_validate_reason_required_destruction")]
CHAIN_COLUMNS = {"chain_version", "chain_prev", "chain_hash"}

INSERT_EVENT = """
INSERT INTO audit_auditevent
    (occurred_at, txid, event_type, actor_label, actor_kind, channel, request_id, reason,
     subject_type, subject_id, changes, schema_version)
VALUES (now(), 1, 'taxon_created', %s, 'system', 'migration', 'mig-1', '',
        'taxon', gen_random_uuid(), '{}', 1)
"""


@pytest.fixture
def back_to_the_leaf() -> Iterator[None]:
    yield
    migrate()  # later tests need the current schema, whatever happened here


def columns(table: str) -> set[str]:
    return {
        name
        for (name,) in query(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = %s",
            [table],
        )
    }


def chained(table: str) -> list[tuple[Any, ...]]:
    return query(
        f"SELECT id, chain_version, chain_prev IS NULL, chain_hash IS NULL"  # noqa: S608
        f" FROM {table} ORDER BY id"
    )


@pytest.mark.usefixtures("back_to_the_leaf")
@pytest.mark.rule("R-AUDIT-01")
def test_the_chain_migration_covers_the_rows_already_there_and_goes_back() -> None:
    migrate(BEFORE)
    assert columns("audit_auditevent") & CHAIN_COLUMNS == set()
    assert columns("audit_rowchange") & CHAIN_COLUMNS == set()

    user = User.objects.create_user("migrating")  # its row changes, written unchained
    query(INSERT_EVENT, ["migration:before-the-chain"])
    query(INSERT_EVENT, ["migration:before-the-chain"])
    query("UPDATE users_user SET last_name = 'Byron' WHERE id = %s", [user.pk])
    before = {
        "events": query("SELECT count(*) FROM audit_auditevent")[0][0],
        "rows": query("SELECT count(*) FROM audit_rowchange")[0][0],
    }
    assert before["events"] >= 2
    assert before["rows"] >= 2

    migrate()
    for table in ("audit_auditevent", "audit_rowchange"):
        assert columns(table) >= CHAIN_COLUMNS, table
        found = chained(table)
        assert len(found) >= 2, table
        # Every row is in the chain, the first links to nothing, no row lacks a hash.
        assert [row[1] for row in found] == [chain.VERSION] * len(found), table
        assert [row[2] for row in found] == [True] + [False] * (len(found) - 1), table
        assert not any(row[3] for row in found), table
    for chained_table, counted in ((chain.EVENT, "events"), (chain.ROW_CHANGE, "rows")):
        walked = chain.walk(chained_table)
        assert walked.first_break is None, (chained_table.name, walked.first_break)
        assert walked.rows == before[counted]

    # The append-only trigger of each chained table is back on after the backfill.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
            " WHERE t.tgname = 'audit_append_only' AND c.relname = ANY(%s) ORDER BY c.relname",
            [["audit_auditevent", "audit_rowchange"]],
        )
        assert [state for (state,) in cursor.fetchall()] == ["O", "O"]
