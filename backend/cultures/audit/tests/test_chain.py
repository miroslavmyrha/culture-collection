"""The hash chain of ADR 0009: every audit row carries it, and a tampered row is found.

The trigger writes the chain, so these tests use the real write paths (a
service, record_batch, Django admin, a data migration and raw SQL as the runtime
role) and then read the chain back with cultures.audit.chain.

Tampering needs what only somebody with database access has: the append-only
trigger refuses UPDATE and DELETE for every role, the owner included, so
`tampered()` switches it off for one statement, which no role but the table's
owner may do. That is the threat ADR 0009 names: the chain "does not stop
someone with database access from changing data, only makes it visible".
"""

import contextlib
import hashlib
import threading
import uuid
from typing import Any

import pytest
from django.db import connection
from django.db.backends.utils import CursorWrapper
from django.test import Client
from django.urls import reverse
from model_bakery import baker

from cultures.audit import chain
from cultures.audit.context import AuditContext, audit_context, audited_atomic, migration_audit
from cultures.audit.events import Change, record_batch, record_event
from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.audit.registry import EVENT_TYPES, EventType
from cultures.core.testing import QueryBaseline, logged_in
from cultures.users.models import User
from cultures.users.services import user_deactivate

pytestmark = pytest.mark.django_db

# Test-only event types, like test_strain_root.py: this module tests the chain, not a service.
ITEM = EventType("test_chain_item", "{actor} changed {subject}")
SUMMARY = EventType("test_chain_summary", "{actor} changed {count} things")


@pytest.fixture(autouse=True)
def chain_types(monkeypatch: pytest.MonkeyPatch) -> None:
    for kind in (ITEM, SUMMARY):
        monkeypatch.setitem(EVENT_TYPES, kind.code, kind)


@pytest.fixture
def staff() -> User:
    """A staff superuser: the person who uses Django admin."""
    user: User = baker.make(
        User, username="staff", email="staff@example.org", is_staff=True, is_superuser=True
    )
    return user


@pytest.fixture
def admin_client(staff: User) -> Client:
    return logged_in(staff)


def change() -> Change:
    return Change("thing", uuid.uuid4(), {"name": [None, "Testella"]})


def tampered(table: str, sql: str, params: list[Any] | None = None) -> None:
    """Run one statement against an append-only table, as only its owner can.

    The append-only trigger of migration 0002 refuses UPDATE and DELETE for every
    role; only the table's owner may switch it off. That is exactly the attacker
    the chain is evidence against.
    """
    with connection.cursor() as cursor:
        # Django defers its foreign key checks, and ALTER TABLE refuses a table with
        # pending trigger events (the roles fixture of conftest.py does the same).
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER audit_append_only")
        try:
            cursor.execute(sql, params)
        finally:
            cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER audit_append_only")


def links() -> list[tuple[int, bytes | None, bytes | None]]:
    """(id, chain_prev, chain_hash) of every event, oldest first."""
    return [
        (row[0], _bytes(row[1]), _bytes(row[2]))
        for row in AuditEvent.objects.order_by("id").values_list("id", "chain_prev", "chain_hash")
    ]


def _bytes(value: Any) -> bytes | None:
    return None if value is None else bytes(value)


@pytest.fixture
def event(member: User, audited: AuditContext) -> AuditEvent:
    """One service write: its event and the row changes of its transaction."""
    user_deactivate(user=member)
    return AuditEvent.objects.get()


@pytest.fixture
def both_chains(member: User, audited: AuditContext) -> None:
    """Rows in both chains: a service write leaves events and row changes, a batch more events."""
    user_deactivate(user=member)
    with audited_atomic():
        record_batch(ITEM, SUMMARY, [change(), change()])


@pytest.fixture
def five_events(audited: AuditContext) -> list[AuditEvent]:
    """Five events in one transaction each, written by both event paths."""
    with audited_atomic():
        record_event(ITEM, change())
        record_event(ITEM, change())
    with audited_atomic():
        record_batch(ITEM, SUMMARY, [change(), change()])
    return list(AuditEvent.objects.order_by("id"))


# Every write path leaves chained rows.


@pytest.mark.rule("R-AUDIT-01")
def test_a_service_write_is_chained_on_both_tables(event: AuditEvent) -> None:
    assert RowChange.objects.exists()
    for table in (chain.EVENT, chain.ROW_CHANGE):
        walked = chain.walk(table)
        assert walked.first_break is None, walked.first_break
        assert walked.rows > 0
    first, *rest = links()
    assert first[1] is None  # the chain's first row links to nothing
    assert all(row[1] is not None for row in rest)


@pytest.mark.rule("R-AUDIT-01")
def test_every_row_of_one_insert_statement_gets_its_own_place(audited: AuditContext) -> None:
    """record_batch writes one INSERT with many rows (bulk_create).

    The trigger reads the head from the table for every row. It sees the rows the
    same statement has already inserted because a plpgsql function is VOLATILE
    (PostgreSQL, "Function Volatility Categories"); if it did not, every row of
    such a statement would chain onto the same predecessor: a fork, not a chain.
    """
    with audited_atomic():
        written = record_batch(ITEM, SUMMARY, [change() for _ in range(50)])
    assert len(written) == 51  # fifty items and the summary, one INSERT
    found = links()
    assert len(found) == 51
    assert len({row[2] for row in found}) == len(found)  # no two rows share a hash
    assert [row[1] for row in found[1:]] == [row[2] for row in found[:-1]]
    assert chain.walk(chain.EVENT).first_break is None


@pytest.mark.rule("R-AUDIT-01")
def test_an_admin_write_is_chained(admin_client: Client, member: User) -> None:
    response = admin_client.post(
        reverse("admin:users_user_change", args=[member.pk]),
        {
            "username": member.username,
            "first_name": "Augusta",
            "last_name": member.last_name,
            "email": member.email,
            "is_active": "on",
        },
    )
    assert response.status_code == 302, response.content
    assert AuditEvent.objects.exists()
    assert RowChange.objects.exists()
    assert chain.walk(chain.EVENT).first_break is None
    assert chain.walk(chain.ROW_CHANGE).first_break is None


@pytest.mark.rule("R-AUDIT-01")
def test_a_data_migration_write_is_chained(member: User) -> None:
    with migration_audit("0099_test", reason="a data migration of a test"):
        User.objects.filter(pk=member.pk).update(last_name="Byron")
        record_event(ITEM, change())
    assert RowChange.objects.filter(request_id__isnull=False).exists()
    assert chain.walk(chain.EVENT).first_break is None
    assert chain.walk(chain.ROW_CHANGE).first_break is None


@pytest.mark.rule("R-AUDIT-01")
def test_raw_sql_as_the_runtime_role_is_chained(member: User, runtime_role: CursorWrapper) -> None:
    """The role the app connects as in production cannot write a row change itself.

    The SECURITY DEFINER row trigger writes it and the chain trigger chains it. The
    walk runs on this connection, so it is proven to need no privilege the runtime
    role lacks.
    """
    runtime_role.execute("UPDATE users_user SET is_staff = true WHERE id = %s", [member.pk])
    walked = chain.walk(chain.ROW_CHANGE)
    assert walked.rows > 0
    assert walked.first_break is None, walked.first_break


# A tampered chain is found, one case per kind of tampering.


@pytest.mark.rule("R-AUDIT-03")
def test_a_changed_column_is_found(five_events: list[AuditEvent]) -> None:
    target = five_events[2]
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET reason = %s WHERE id = %s",
        ["rewritten", target.pk],
    )
    found = chain.walk(chain.EVENT).first_break
    assert found is not None
    assert (found.kind, found.row_id) == (chain.CONTENT_MISMATCH, target.pk)
    assert "a column was changed" in found.detail


@pytest.mark.rule("R-AUDIT-03")
def test_a_removed_row_is_found(five_events: list[AuditEvent]) -> None:
    target, after = five_events[2], five_events[3]
    tampered("audit_auditevent", "DELETE FROM audit_auditevent WHERE id = %s", [target.pk])
    found = chain.walk(chain.EVENT).first_break
    assert found is not None
    assert (found.kind, found.row_id) == (chain.PREV_MISMATCH, after.pk)
    assert "a row was removed" in found.detail


@pytest.mark.rule("R-AUDIT-03")
def test_a_forged_hash_is_found(five_events: list[AuditEvent]) -> None:
    target = five_events[2]
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET chain_hash = sha256('forged') WHERE id = %s",
        [target.pk],
    )
    found = chain.walk(chain.EVENT).first_break
    assert found is not None
    assert (found.kind, found.row_id) == (chain.CONTENT_MISMATCH, target.pk)
    assert "the hash was forged" in found.detail


@pytest.mark.rule("R-AUDIT-03")
def test_a_changed_row_whose_hash_was_recomputed_breaks_the_next_row(
    five_events: list[AuditEvent],
) -> None:
    """Recomputing the row's own hash moves the break: the next row still points at the
    old one. Rewriting the whole chain from there on is what the anchors are for."""
    target, after = five_events[2], five_events[3]
    recomputed = chain.hash_sql(chain.EVENT, chain.VERSION, "audit_auditevent", "chain_prev")
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET reason = 'rewritten' WHERE id = %s",
        [target.pk],
    )
    tampered(
        "audit_auditevent",
        f"UPDATE audit_auditevent SET chain_hash = {recomputed} WHERE id = %s",  # noqa: S608
        [target.pk],
    )
    found = chain.walk(chain.EVENT).first_break
    assert found is not None
    assert (found.kind, found.row_id) == (chain.PREV_MISMATCH, after.pk)


@pytest.mark.rule("R-AUDIT-03")
def test_a_reordered_pair_is_found(five_events: list[AuditEvent]) -> None:
    """Two neighbouring rows exchange their content: both hashes stop matching."""
    one, two = five_events[2], five_events[3]
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent AS a SET subject_type = b.subject_type, subject_id = b.subject_id"
        " FROM audit_auditevent b WHERE (a.id, b.id) IN ((%s, %s), (%s, %s))",
        [one.pk, two.pk, two.pk, one.pk],
    )
    found = chain.walk(chain.EVENT).first_break
    assert found is not None
    assert (found.kind, found.row_id) == (chain.CONTENT_MISMATCH, one.pk)


@pytest.mark.rule("R-AUDIT-03")
def test_a_row_with_no_hash_is_found(five_events: list[AuditEvent]) -> None:
    target = five_events[2]
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET chain_hash = NULL WHERE id = %s",
        [target.pk],
    )
    found = chain.walk(chain.EVENT).first_break
    assert found is not None
    assert (found.kind, found.row_id) == (chain.NO_HASH, target.pk)


@pytest.mark.rule("R-AUDIT-03")
def test_a_chain_version_this_build_does_not_know_is_found(five_events: list[AuditEvent]) -> None:
    target = five_events[2]
    tampered(
        "audit_auditevent",
        "UPDATE audit_auditevent SET chain_version = 7 WHERE id = %s",
        [target.pk],
    )
    found = chain.walk(chain.EVENT).first_break
    assert found is not None
    assert (found.kind, found.row_id) == (chain.UNKNOWN_VERSION, target.pk)


# The chain columns are the database's, not the writer's.


@pytest.mark.rule("R-AUDIT-02")
def test_the_runtime_role_cannot_choose_the_chain_columns(
    five_events: list[AuditEvent], runtime_role: CursorWrapper
) -> None:
    """The runtime role may insert events (APP_ROLE_GRANTS). The BEFORE INSERT trigger
    replaces whatever it passes in the three chain columns, so it can place a row only
    at the head of the chain and cannot give it a hash of its own."""
    head = chain.head(chain.EVENT)
    assert head is not None
    chosen = bytes.fromhex("11" * 32)
    runtime_role.execute(
        "INSERT INTO audit_auditevent (occurred_at, txid, event_type, actor_label, actor_kind,"
        " channel, request_id, reason, subject_type, subject_id, changes, schema_version,"
        " chain_version, chain_prev, chain_hash)"
        " VALUES (now(), 1, 'test_chain_item', 'command:forge', 'system', 'command', 'forge', '',"
        " 'thing', gen_random_uuid(), '{}', 1, 7, %s, %s)"
        " RETURNING id, chain_version, chain_prev, chain_hash",
        [chosen, chosen],
    )
    row_id, version, prev, stored = runtime_role.fetchone()
    assert version == chain.VERSION
    assert bytes(prev) == head[1]
    assert bytes(stored) != chosen
    walked = chain.walk(chain.EVENT)
    assert walked.first_break is None, walked.first_break
    assert walked.head_id == row_id


@pytest.mark.rule("R-AUDIT-02")
def test_a_multi_row_insert_outside_the_services_is_still_one_chain(
    five_events: list[AuditEvent], runtime_role: CursorWrapper
) -> None:
    """Three rows in one statement, written by the role the app connects as, each with
    its own place: the trigger's head read sees the rows the same statement already
    wrote. A script that inserts events in bulk cannot fork the chain either."""
    before = len(five_events)
    runtime_role.execute(
        "INSERT INTO audit_auditevent (occurred_at, txid, event_type, actor_label, actor_kind,"
        " channel, request_id, reason, subject_type, subject_id, changes, schema_version)"
        " SELECT now(), 1, 'test_chain_item', 'command:bulk', 'system', 'command', 'bulk', '',"
        " 'thing', gen_random_uuid(), '{}', 1 FROM generate_series(1, 3)"
    )
    found = links()
    assert len(found) == before + 3
    assert len({row[2] for row in found}) == len(found)
    assert [row[1] for row in found[1:]] == [row[2] for row in found[:-1]]
    assert chain.walk(chain.EVENT).first_break is None


@pytest.mark.rule("R-AUDIT-02")
def test_every_column_of_a_chained_table_is_in_the_chain() -> None:
    """A new column on an audit table must join the chain, or rows written before and
    after it would be hashed over different content. It joins as a new version in
    cultures.audit.chain with a trigger of its own, so the rows already written keep
    verifying and the anchors over them keep matching."""
    for table in chain.CHAINS.values():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = %s",
                [table.table],
            )
            columns = {name for (name,) in cursor.fetchall()}
        assert columns, table.table
        assert columns == table.column_names(), table.table


def test_the_chain_of_a_table_with_no_rows_is_intact() -> None:
    walked = chain.walk(chain.EVENT)
    assert (walked.rows, walked.head_id, walked.first_break) == (0, None, None)
    assert chain.head(chain.EVENT) is None


# The canonical content is the same text in every session, and it is this text.


def recomputed() -> list[tuple[str, int, bytes | None, bytes | None]]:
    """(chain, id, the stored hash, the hash recomputed now) for every row of both chains."""
    found: list[tuple[str, int, bytes | None, bytes | None]] = []
    for table in chain.CHAINS.values():
        expression = chain.hash_sql(table, chain.VERSION, "a", "a.chain_prev")
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT a.id, a.chain_hash, {expression} FROM public.{table.table} a"  # noqa: S608
                " ORDER BY a.id"
            )
            found += [
                (table.name, row[0], _bytes(row[1]), _bytes(row[2])) for row in cursor.fetchall()
            ]
    return found


@pytest.mark.rule("R-AUDIT-01")
@pytest.mark.rule("R-AUDIT-03")
def test_the_hash_does_not_depend_on_the_sessions_time_settings(both_chains: None) -> None:
    """A verifier years later runs in another session, maybe on a server in another zone.

    Every timestamp of the payload goes through `to_char(... AT TIME ZONE 'UTC', ...)`
    (`chain.STAMP`), never a cast to text, whose form follows the session's TimeZone and
    DateStyle. Without that, a verifier run from another job, or the same job after the
    server's zone changed, would report a break over the whole history: the worst failure
    a chain meant to be read years later can have, and a silent one, because the trigger
    and the verifier agree inside any one session. `stmt_at` of the row changes goes
    through the same stamp, so both chains are checked here.
    """
    before = recomputed()
    assert {row[0] for row in before} == set(chain.CHAINS)  # both chains have rows
    assert all(stored == computed for _, _, stored, computed in before)
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'America/New_York'")
        cursor.execute("SET LOCAL DateStyle TO 'German, DMY'")
        cursor.execute("SELECT current_setting('TimeZone'), current_setting('DateStyle')")
        assert cursor.fetchone() == ("America/New_York", "German, DMY")
    assert recomputed() == before
    for table in chain.CHAINS.values():
        walked = chain.walk(table)
        assert walked.rows > 0, table.name
        assert walked.first_break is None, (table.name, walked.first_break)


# One row of each chain, written out: the payload of version 1 is this text and no other.
# A change to it (another separator, another order, a column added or dropped) is a new
# version with its own trigger, because every row already written was hashed over this form
# and every anchor stamped a head computed from it.
EVENT_ROW = """
SELECT 1::smallint AS chain_version, 7::bigint AS id,
       '2026-11-04 01:02:03.456789+00'::timestamptz AS occurred_at,
       99::bigint AS txid, 'taxon_created'::varchar AS event_type,
       NULL::bigint AS actor_id, 'command:probe'::varchar AS actor_label,
       'system'::varchar AS actor_kind, NULL::bigint AS lab_id,
       '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0'::uuid AS strain_id,
       'command'::varchar AS channel, 'req-1'::varchar AS request_id,
       NULL::uuid AS batch_id, 'a reason with ", a comma and null'::text AS reason,
       'taxon'::varchar AS subject_type,
       '11111111-2222-3333-4444-555555555555'::uuid AS subject_id,
       '{"b": 1, "a": [2, 3.0]}'::jsonb AS changes, 1::smallint AS schema_version
"""
ROW_CHANGE_ROW = """
SELECT 1::smallint AS chain_version, 8::bigint AS id,
       '2026-11-04 01:02:03.456789+00'::timestamptz AS occurred_at,
       '2026-11-04 01:02:03.654321+00'::timestamptz AS stmt_at,
       99::bigint AS txid, 'users.user'::varchar AS table_label,
       '5'::text AS row_pk, 'UPDATE'::varchar AS op,
       '{"first_name": "personal"}'::jsonb AS old, NULL::jsonb AS new,
       NULL::bigint AS actor_id, false AS actor_claim_invalid,
       NULL::varchar AS request_id, 'cultures'::varchar AS db_role,
       'cultures'::varchar AS db_application
"""
PAYLOADS = {
    chain.EVENT.name: (
        EVENT_ROW,
        '["aa", "1", "7", "2026-11-04 01:02:03.456789", "99", "taxon_created", null,'
        ' "command:probe", "system", null, "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0", "command",'
        ' "req-1", null, "a reason with \\", a comma and null", "taxon",'
        ' "11111111-2222-3333-4444-555555555555", "{\\"a\\": [2, 3.0], \\"b\\": 1}", "1"]',
    ),
    chain.ROW_CHANGE.name: (
        ROW_CHANGE_ROW,
        '["aa", "1", "8", "2026-11-04 01:02:03.456789", "2026-11-04 01:02:03.654321", "99",'
        ' "users.user", "5", "UPDATE", "{\\"first_name\\": \\"personal\\"}", null, null,'
        ' "false", null, "cultures", "cultures"]',
    ),
}


@pytest.mark.parametrize("name", sorted(PAYLOADS))
@pytest.mark.rule("R-AUDIT-01")
def test_the_canonical_content_of_a_row_is_the_documented_text(name: str) -> None:
    """The timestamps are UTC whatever the session says, the jsonb keys are sorted, a NULL
    is `null` and not the text "null", and a value holding a quote or a comma cannot look
    like two values.

    The digest is checked against Python's hashlib over the same text, not against a hex
    literal: it proves the hash is sha256 of exactly those UTF-8 bytes, so a verifier
    written outside PostgreSQL years later can reproduce it from this file alone.
    """
    table = chain.CHAINS[name]
    row, expected = PAYLOADS[name]
    payload = chain.payload_sql(table, chain.VERSION, "a", "decode('aa', 'hex')")
    digest = chain.hash_sql(table, chain.VERSION, "a", "decode('aa', 'hex')")
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL TIME ZONE 'America/New_York'")
        cursor.execute("SET LOCAL DateStyle TO 'German, DMY'")
        cursor.execute(f"SELECT {payload}, {digest} FROM ({row}) a")  # noqa: S608 (constants here)
        found = cursor.fetchone()
    assert found is not None
    assert found[0] == expected
    assert bytes(found[1]) == hashlib.sha256(expected.encode()).digest()


# The chain costs no query: it is written and read inside the database.


@pytest.mark.parametrize("size", [1, 7])
@pytest.mark.rule("R-AUDIT-01")
def test_the_chain_adds_no_query_per_audit_row(
    audited: AuditContext, query_baseline: QueryBaseline, size: int
) -> None:
    """One key for both sizes: the baseline tool fails when the count grows with the data."""
    changes = [change() for _ in range(size)]
    with query_baseline("record_batch"), audited_atomic():
        record_batch(ITEM, SUMMARY, changes)


def test_an_audited_service_write_keeps_its_query_count(
    member: User, audited: AuditContext, query_baseline: QueryBaseline
) -> None:
    with query_baseline("user_deactivate"):
        user_deactivate(user=member)


# Two transactions appending at once make one chain, not a fork.

AFTER_INSERT_WAIT = 1.5  # seconds the thread that holds the lock waits for the other one


def _wait(barrier: threading.Barrier) -> None:
    """A meeting point the other thread may never reach: the timeout is the signal."""
    with contextlib.suppress(threading.BrokenBarrierError):
        barrier.wait()


@pytest.mark.django_db(transaction=True)
@pytest.mark.slow
@pytest.mark.rule("R-AUDIT-02")
def test_two_transactions_appending_at_once_make_one_chain() -> None:
    """Both threads are inside their transactions before either appends (`at_start`).

    The first one past its INSERT waits for the other (`after_insert`). The chain's
    advisory lock is held until commit, so the second thread cannot be there and the
    wait times out; afterwards it reads the committed head. Without the lock both read
    the same head, both pass `after_insert` at once and the chain forks, which the walk
    reports as a break on every run, not only on an unlucky one.
    """
    at_start = threading.Barrier(2, timeout=5)
    after_insert = threading.Barrier(2, timeout=AFTER_INSERT_WAIT)
    outcomes: dict[int, str] = {}

    def append(index: int) -> None:
        try:
            with audit_context(
                channel=Channel.COMMAND,
                actor_kind=ActorKind.SYSTEM,
                actor_label=f"command:append-{index}",
            ):
                _wait(at_start)
                with audited_atomic():
                    record_event(ITEM, change())
                    _wait(after_insert)
            outcomes[index] = "done"
        finally:
            connection.close()

    threads = [threading.Thread(target=append, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert outcomes == {1: "done", 2: "done"}
    found = links()
    assert len(found) == 2
    assert found[0][1] is None
    assert found[1][1] == found[0][2]  # the second row chains onto the first, not beside it
    walked = chain.walk(chain.EVENT)
    assert walked.first_break is None, walked.first_break
