"""The hash chain over the audit rows and its verification (ADR 0009, #175).

ADR 0009 decides that every audit row joins a hash chain: "each row's hash covers
its content and the previous hash, so a row edited, removed or inserted inside
the database breaks the chain from that point". This module says what the chain
is and reads it back; the database writes it (audit migration 0034).

**Two chains, one per table** (`CHAINS`): the service events and the row changes.
Not one chain over both, because the two tables are written by different roles in
one transaction (the app inserts events, the SECURITY DEFINER row trigger writes
row changes) and nothing records how the two interleaved: `occurred_at` is the
transaction's start time on both rows, the same value for every row of a
transaction. A chain needs a total order that can be read back years later, and
each table has exactly one such order in its own identity column.

**Where the hash is computed**: a BEFORE INSERT trigger per table. A trigger is
the only place a write past the services cannot skip, which is the point of the
chain; computing it in Python would leave `bulk_create`, `QuerySet.update()`,
raw SQL, COPY and psql sessions outside it. The digest is PostgreSQL's built-in
`sha256(bytea)` (PostgreSQL 11 and later; checked on the project's
postgres:18-alpine image, PostgreSQL 18.6), so no extension has to be created
and the migration role needs no privilege for one. pgcrypto is available in the
image but buys nothing here.

**The canonical content** is a JSON array of text built in SQL, the previous
row's hash first, then the columns of `Chain.columns` in that order:

    sha256(convert_to(jsonb_build_array(encode(prev,'hex'), c1, c2, ...)::text, 'UTF8'))

A JSON array keeps the order, separates the elements unambiguously (a value that
contains a separator cannot look like two values) and tells a NULL from the text
"null". Every element is cast to text, so the encoding never changes with the
column's type. A timestamp is never cast to text directly: that form depends on
the session's TimeZone and DateStyle, so two sessions would hash one row
differently; `STAMP` formats it in UTC with microseconds. `changes`, `old` and
`new` are jsonb, whose text form is already canonical (keys sorted, one
spelling per number).

None of that is held by the trigger and this module agreeing: they agree inside
any one session even when both are wrong together, and every row of a test
database is written by the trigger under test, so a wrong form stays green and
only breaks a verifier in another session or another year. Two tests hold it
instead (`tests/test_chain.py`): one writes rows and verifies both chains in a
session with another TimeZone and DateStyle, and one writes version 1's payload
out in full for both chains and checks the digest against Python's hashlib, so a
verifier outside PostgreSQL can reproduce it.

`chain_prev` and `chain_hash` are not in the payload: a row cannot hash itself.
`chain_version` is, so nobody can move a row to another payload definition
without breaking its hash.

**Why a version**: an audit table that gains a column later would otherwise make
every earlier row unverifiable, because the payload would cover a column the old
rows were not hashed with, and re-chaining the table would void every anchor
that exists. A new column therefore adds a `Chain` version with its own column
list and its own trigger migration; rows keep the version they were written
with. `tests/test_chain.py` fails while a column of an audit table is in no
version, so the decision cannot be forgotten.

**Concurrency**: one advisory lock for both chains (`LOCK`), taken by
`audited_atomic()` at the start of every audited transaction and again by the
triggers for writes that come from outside the application. Two transactions
can then never read the same previous row. One key for both chains, so a
transaction that appends to the events and to the row changes can never take two
chain locks in opposite orders. The lock is held until commit, so every audited
write serialises; a lab register is not a write-heavy system, and a chain per
table has no cheaper serialisation point (ADR 0009, amendment of 2026-11-04).

Each append reads the head from the table, also inside one INSERT statement with
many rows (`record_batch` uses `bulk_create`): a plpgsql function is VOLATILE,
and PostgreSQL's "Function Volatility Categories" says such a function sees the
data changes made by the SQL command that calls it, because it takes "a fresh
snapshot at the start of each query they execute". Nothing is cached in a session
setting, which a session could then forge: measured on PostgreSQL 18.6, 2001
events in one `bulk_create` take 0.43 to 0.54 s either way.

**Verification** (`walk`) reads the rows back in id order and checks two things
per row: that `chain_prev` is the previous row's `chain_hash` (NULL for the first
row), and that `chain_hash` is the digest over the stored content. The first
catches a removed or reordered row, the second a changed column or a forged
hash. The SQL is built here, not called as a stored function, so somebody who
replaces the trigger cannot change what the verifier computes.

**The anchors** (`verify`) are the outside evidence the chain alone cannot be: a
chain its editor can recompute proves nothing (ADR 0009, Alternatives
considered). Each anchor names a row of the chain and the hash that row held when
a timestamp authority stamped it, so a head that is gone, a head that now hashes
to something else, or a break inside stamped history is reported as such.
Writing them is `cultures.audit.anchors`.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import connection

# One lock for both chains (see the module docstring). hashtextextended is the
# project's way of turning a name into an advisory lock key (storage migration 0003).
LOCK = "pg_advisory_xact_lock(hashtextextended('audit_chain', 0))"

# How a column becomes one element of the payload array. {ref} is the column reference.
TEXT = "{ref}::text"
STAMP = "pg_catalog.to_char({ref} AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')"

# The columns the chain never covers: a row cannot hash its own hash.
CHAIN_COLUMNS = ("chain_prev", "chain_hash")

VERSION = 1  # what the triggers of migration 0034 write


@dataclass(frozen=True)
class Chain:
    """One table's chain. `columns` is the payload, in order; never reorder a version."""

    name: str
    table: str
    versions: dict[int, tuple[tuple[str, str], ...]]

    def columns(self, version: int) -> tuple[tuple[str, str], ...] | None:
        return self.versions.get(version)

    def column_names(self) -> set[str]:
        """Every column any version hashes, plus the two it cannot."""
        return {name for columns in self.versions.values() for name, _ in columns} | set(
            CHAIN_COLUMNS
        )


EVENT = Chain(
    "event",
    "audit_auditevent",
    {
        1: (
            ("chain_version", TEXT),
            ("id", TEXT),
            ("occurred_at", STAMP),
            ("txid", TEXT),
            ("event_type", TEXT),
            ("actor_id", TEXT),
            ("actor_label", TEXT),
            ("actor_kind", TEXT),
            ("lab_id", TEXT),
            ("strain_id", TEXT),
            ("channel", TEXT),
            ("request_id", TEXT),
            ("batch_id", TEXT),
            ("reason", TEXT),
            ("subject_type", TEXT),
            ("subject_id", TEXT),
            ("changes", TEXT),
            ("schema_version", TEXT),
        )
    },
)

ROW_CHANGE = Chain(
    "row_change",
    "audit_rowchange",
    {
        1: (
            ("chain_version", TEXT),
            ("id", TEXT),
            ("occurred_at", STAMP),
            ("stmt_at", STAMP),
            ("txid", TEXT),
            ("table_label", TEXT),
            ("row_pk", TEXT),
            ("op", TEXT),
            ("old", TEXT),
            ("new", TEXT),
            ("actor_id", TEXT),
            ("actor_claim_invalid", TEXT),
            ("request_id", TEXT),
            ("db_role", TEXT),
            ("db_application", TEXT),
        )
    },
)

CHAINS: dict[str, Chain] = {chain.name: chain for chain in (EVENT, ROW_CHANGE)}


def payload_sql(chain: Chain, version: int, alias: str, prev: str) -> str:
    """The canonical content of one row as a SQL text expression."""
    columns = chain.columns(version)
    if columns is None:
        raise ValueError(f"chain {chain.name!r} has no version {version}")
    parts = [f"pg_catalog.encode({prev}, 'hex')"]
    parts += [kind.format(ref=f"{alias}.{name}") for name, kind in columns]
    return "pg_catalog.jsonb_build_array(" + ", ".join(parts) + ")::text"


def hash_sql(chain: Chain, version: int, alias: str, prev: str) -> str:
    """The row's hash as a SQL bytea expression: sha256 over the canonical content."""
    payload = payload_sql(chain, version, alias, prev)
    return f"pg_catalog.sha256(pg_catalog.convert_to({payload}, 'UTF8'))"


def _computed_sql(chain: Chain, alias: str) -> str:
    """The hash of every version, chosen by the row's own chain_version.

    An unknown version yields NULL, which matches no stored hash, so the row is
    reported as a break instead of being skipped.
    """
    cases = " ".join(
        f"WHEN {version} THEN {hash_sql(chain, version, alias, f'{alias}.chain_prev')}"
        for version in sorted(chain.versions)
    )
    return f"CASE {alias}.chain_version {cases} END"


# Breaks, in the order the verifier reports them.
NO_HASH = "no_hash"  # the row carries no chain hash at all
UNKNOWN_VERSION = "unknown_version"
PREV_MISMATCH = "prev_mismatch"  # chain_prev is not the previous row's hash
CONTENT_MISMATCH = "content_mismatch"  # the content does not hash to chain_hash


@dataclass(frozen=True)
class Break:
    kind: str
    chain: str
    row_id: int
    detail: str


@dataclass(frozen=True)
class Walked:
    """What one walk of a chain found: the first break, the row count and the head."""

    chain: str
    rows: int
    head_id: int | None
    head_hash: bytes | None
    first_break: Break | None


def _hex(value: bytes | None) -> str:
    return "none" if value is None else value.hex()


def _bytes(value: Any) -> bytes | None:
    return None if value is None else bytes(value)


def _rows(chain: Chain, batch: int) -> Iterator[tuple[int, int, Any, Any, Any]]:
    """(id, chain_version, chain_prev, chain_hash, the recomputed hash) in id order.

    Read in batches, so a chain of millions of rows never loads at once. The
    recomputed hash is this module's expression, inlined in the query: nobody who
    replaces a stored function changes what the verifier computes.
    """
    read = f"a.id, a.chain_version, a.chain_prev, a.chain_hash, {_computed_sql(chain, 'a')}"
    # The table name and the expression are this module's own constants, never input.
    sql = (
        f"SELECT {read} FROM public.{chain.table} a"  # noqa: S608
        " WHERE a.id > %s ORDER BY a.id LIMIT %s"
    )
    after = 0
    while True:
        with connection.cursor() as cursor:
            cursor.execute(sql, [after, batch])
            found = cursor.fetchall()
        if not found:
            return
        yield from found
        after = found[-1][0]


def walk(chain: Chain, *, batch: int = 5000) -> Walked:
    """Read one chain back and report its first break.

    Two checks per row: `chain_prev` is the previous row's `chain_hash` (null for
    the first row of the chain), and `chain_hash` is the digest over the row's
    stored content. The first catches a row removed, inserted or reordered, the
    second a changed column or a forged hash. Reads only, so any role with SELECT
    on the table may run it.
    """
    previous: bytes | None = None
    rows = 0
    head_id: int | None = None
    found: Break | None = None
    for row_id, version, prev, stored, computed in _rows(chain, batch):
        rows += 1
        head_id, before = row_id, previous
        previous = _bytes(stored)
        if found is not None:
            continue
        if stored is None:
            found = Break(NO_HASH, chain.name, row_id, "the row carries no chain hash")
        elif chain.columns(version) is None:
            found = Break(
                UNKNOWN_VERSION,
                chain.name,
                row_id,
                f"chain version {version} is unknown to this build",
            )
        elif _bytes(prev) != before:
            found = Break(
                PREV_MISMATCH,
                chain.name,
                row_id,
                f"chain_prev is {_hex(_bytes(prev))}, the row before it hashes to"
                f" {_hex(before)}: a row was removed, inserted or reordered",
            )
        elif _bytes(stored) != _bytes(computed):
            found = Break(
                CONTENT_MISMATCH,
                chain.name,
                row_id,
                f"chain_hash is {_hex(_bytes(stored))}, the row's content hashes to"
                f" {_hex(_bytes(computed))}: a column was changed, or the hash was forged",
            )
    return Walked(chain.name, rows, head_id, previous, found)


def head(chain: Chain) -> tuple[int, bytes] | None:
    """The last row of the chain, or None while the table is empty."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT a.id, a.chain_hash FROM public.{chain.table} a"  # noqa: S608 (a constant)
            " ORDER BY a.id DESC LIMIT 1"
        )
        row = cursor.fetchone()
    if row is None or row[1] is None:
        return None
    return row[0], bytes(row[1])


# Anchor findings: what the stamped heads say about the chain as it is now.
ANCHOR_ROW_GONE = "anchor_row_gone"
ANCHOR_HASH_MISMATCH = "anchor_hash_mismatch"
ANCHOR_COVERS_BREAK = "anchor_covers_break"


@dataclass(frozen=True)
class Anchor:
    id: int
    chain: str
    head_id: int
    head_hash: bytes
    anchored_at: datetime
    authority: str
    token_time: datetime | None


@dataclass(frozen=True)
class AnchorFinding:
    kind: str
    chain: str
    anchor_id: int
    head_id: int
    detail: str


@dataclass(frozen=True)
class Report:
    """One chain as the verifier found it: the walk, the anchors and what is wrong."""

    walked: Walked
    anchors: list[Anchor]
    findings: list[AnchorFinding]

    @property
    def chain(self) -> str:
        return self.walked.chain

    @property
    def intact(self) -> bool:
        return self.walked.first_break is None and not self.findings


def anchors(chain: Chain) -> list[Anchor]:
    """Every anchor of this chain, the oldest head first."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, chain, head_id, head_hash, anchored_at, authority, token_time"
            " FROM public.audit_chainanchor WHERE chain = %s ORDER BY head_id, id",
            [chain.name],
        )
        return [
            Anchor(row[0], row[1], row[2], bytes(row[3]), row[4], row[5], row[6])
            for row in cursor.fetchall()
        ]


def _stored_hash(chain: Chain, row_id: int) -> bytes | None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT a.chain_hash FROM public.{chain.table} a WHERE a.id = %s",  # noqa: S608
            [row_id],
        )
        row = cursor.fetchone()
    return None if row is None or row[0] is None else bytes(row[0])


def _findings(chain: Chain, found: list[Anchor], broken: Break | None) -> list[AnchorFinding]:
    """What each anchor says about the rows as they are now.

    An anchor is outside evidence: the token covers the head's hash at a time a
    trust service provider asserts. A head that is gone, a head that now hashes to
    something else, or a break inside history an anchor covers is therefore not
    only a break but a break in stamped history (ADR 0009: "the stamped heads then
    no longer match").
    """
    results: list[AnchorFinding] = []
    for one in found:
        stored = _stored_hash(chain, one.head_id)
        if stored is None:
            results.append(
                AnchorFinding(
                    ANCHOR_ROW_GONE,
                    chain.name,
                    one.id,
                    one.head_id,
                    f"the anchored row {one.head_id} is gone",
                )
            )
        elif stored != one.head_hash:
            results.append(
                AnchorFinding(
                    ANCHOR_HASH_MISMATCH,
                    chain.name,
                    one.id,
                    one.head_id,
                    f"row {one.head_id} hashes to {_hex(stored)}, the anchor stamped"
                    f" {_hex(one.head_hash)}",
                )
            )
        if broken is not None and broken.row_id <= one.head_id:
            results.append(
                AnchorFinding(
                    ANCHOR_COVERS_BREAK,
                    chain.name,
                    one.id,
                    one.head_id,
                    f"the break at row {broken.row_id} is inside history stamped at"
                    f" {one.anchored_at.isoformat()} by {one.authority}",
                )
            )
    return results


def verify(chain: Chain, *, batch: int = 5000) -> Report:
    """Walk one chain and check it against its anchors. Reads only."""
    walked = walk(chain, batch=batch)
    found = anchors(chain)
    return Report(walked, found, _findings(chain, found, walked.first_break))
