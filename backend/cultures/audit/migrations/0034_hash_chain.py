"""Every audit row carries the hash of its content and of the row before it (ADR 0009, #175).

What the chain is, why there is one per table, how the canonical content is
built and how it is read back: cultures/audit/chain.py. This migration adds the
three columns, the two BEFORE INSERT triggers that write them, and the chain over
the rows that are already there.

The hash is PostgreSQL's built-in sha256(bytea) (PostgreSQL 11 and later),
so no extension is created and the migration role needs no privilege for one.

The triggers replace whatever an insert passes in the three columns, so no role
can choose a row's place in the chain, and the runtime role keeps its plain
table-level INSERT grant.

Each trigger takes one advisory lock for both chains before it reads the head:
two transactions must never read the same previous row, and one key for both
chains keeps a transaction that appends to both from taking two chain locks in
opposite orders. audited_atomic() takes the same lock in its set_config
statement, so an audited transaction holds it before any domain lock.

The head is read from the table for every row, also inside one INSERT statement
with many rows (record_batch uses bulk_create). That works because a plpgsql
function is VOLATILE and PostgreSQL's "Function Volatility Categories" says a
VOLATILE function sees the data changes made by the SQL command that calls it,
taking "a fresh snapshot at the start of each query they execute", and a BEFORE
ROW trigger runs after the previous rows of its own statement are in. Measured
on PostgreSQL 18.6: 2001 events in one bulk_create take 0.43 to 0.54 s, the same
with and without a per-transaction cache of the head, so nothing is kept in a
session setting that a session could then forge.

The rows already in the database are chained here, with the append-only trigger
disabled for the length of the migration (the migration role is a member of the
audit owner, so it may). A database that already holds rows therefore gets a
chain over all of them, computed from their current content: it proves nothing
about what happened to those rows before this migration, which is exactly why
ADR 0009 asks for the chain before the first production data. There is no
production database yet; development, seed and test databases hold the rows this
backfills. Nothing is anchored yet, so no outside evidence is voided.

A migration that replaces one of these function bodies starts from FORWARD here
(the latest migration that wrote them) and uses FORWARD as its own REVERSE. A new
column on an audit table does not change these functions: it adds a version to
cultures.audit.chain and a trigger of its own, so the rows written before it stay
verifiable and the anchors over them keep matching.
"""

from django.db import migrations, models

EVENT_HASH = (
    "pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.jsonb_build_array("
    "pg_catalog.encode(prev, 'hex'), {a}.chain_version::text, {a}.id::text,"
    " pg_catalog.to_char({a}.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'),"
    " {a}.txid::text, {a}.event_type::text, {a}.actor_id::text, {a}.actor_label::text,"
    " {a}.actor_kind::text, {a}.lab_id::text, {a}.strain_id::text, {a}.channel::text,"
    " {a}.request_id::text, {a}.batch_id::text, {a}.reason::text, {a}.subject_type::text,"
    " {a}.subject_id::text, {a}.changes::text, {a}.schema_version::text)::text, 'UTF8'))"
)
ROW_HASH = (
    "pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.jsonb_build_array("
    "pg_catalog.encode(prev, 'hex'), {a}.chain_version::text, {a}.id::text,"
    " pg_catalog.to_char({a}.occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'),"
    " pg_catalog.to_char({a}.stmt_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'),"
    " {a}.txid::text, {a}.table_label::text, {a}.row_pk::text, {a}.op::text, {a}.old::text,"
    " {a}.new::text, {a}.actor_id::text, {a}.actor_claim_invalid::text, {a}.request_id::text,"
    " {a}.db_role::text, {a}.db_application::text)::text, 'UTF8'))"
)

APPEND = """
CREATE FUNCTION audit_chain_{chain}() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    prev bytea;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('audit_chain', 0));
    SELECT a.chain_hash INTO prev FROM public.{table} a ORDER BY a.id DESC LIMIT 1;
    NEW.chain_version := 1;
    NEW.chain_prev := prev;
    NEW.chain_hash := {hash};
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION audit_chain_{chain}() FROM PUBLIC;
CREATE TRIGGER audit_chain BEFORE INSERT ON {table}
    FOR EACH ROW EXECUTE FUNCTION audit_chain_{chain}();
"""

DROP_APPEND = """
DROP TRIGGER audit_chain ON {table};
DROP FUNCTION audit_chain_{chain}();
"""

# The rows already there, in id order. A loop, not one statement: each row's hash
# needs the hash of the row before it, and the only database that runs this with
# rows in it is a development, seed or test database.
BACKFILL = """
ALTER TABLE {table} DISABLE TRIGGER audit_append_only;
DO $$
DECLARE
    prev bytea;
    row_id bigint;
BEGIN
    FOR row_id IN SELECT a.id FROM public.{table} a ORDER BY a.id LOOP
        UPDATE public.{table} AS e
           SET chain_prev = prev, chain_hash = {hash}
         WHERE e.id = row_id
        RETURNING e.chain_hash INTO prev;
    END LOOP;
END;
$$;
ALTER TABLE {table} ENABLE TRIGGER audit_append_only;
"""

CHAINS = (
    ("event", "audit_auditevent", EVENT_HASH),
    ("rowchange", "audit_rowchange", ROW_HASH),
)

FORWARD = "".join(
    APPEND.format(chain=chain, table=table, hash=expression.format(a="NEW"))
    for chain, table, expression in CHAINS
)
REVERSE = "".join(DROP_APPEND.format(chain=chain, table=table) for chain, table, _ in CHAINS)
FILL = "".join(
    BACKFILL.format(table=table, hash=expression.format(a="e")) for _, table, expression in CHAINS
)


class Migration(migrations.Migration):
    dependencies = [("audit", "0033_validate_reason_required_destruction")]

    operations = [
        migrations.AddField(
            model_name="auditevent", name="chain_hash", field=models.BinaryField(null=True)
        ),
        migrations.AddField(
            model_name="auditevent", name="chain_prev", field=models.BinaryField(null=True)
        ),
        migrations.AddField(
            model_name="auditevent",
            name="chain_version",
            field=models.PositiveSmallIntegerField(db_default=1),
        ),
        migrations.AddField(
            model_name="rowchange", name="chain_hash", field=models.BinaryField(null=True)
        ),
        migrations.AddField(
            model_name="rowchange", name="chain_prev", field=models.BinaryField(null=True)
        ),
        migrations.AddField(
            model_name="rowchange",
            name="chain_version",
            field=models.PositiveSmallIntegerField(db_default=1),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
    ]
