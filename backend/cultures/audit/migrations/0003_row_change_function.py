"""The row audit trigger functions. Tables attach them with cultures.audit.operations.

audit_row_change(label, pk_columns_json, excluded...) writes one
audit_rowchange row per changed row:
- table_label is the label argument, stable across table renames and restores
  (TG_TABLE_NAME and the table oid are not);
- row_pk is the primary key as text, a JSON array of the values for a composite
  key; never ctid, which changes on every update;
- INSERT stores the new row, DELETE the old row, UPDATE only the columns whose
  value changed, old and new. Excluded columns are removed first, in all three,
  and an UPDATE that changes only excluded columns writes no row;
- actor_id and request_id come from audited_atomic()'s set_config. Outside it
  (psql, a script, a forgotten service) they are null, which is the alarm.
  NULLIF is required: after a transaction that set them ends, current_setting()
  returns '' for the rest of the session, not null (checked on PostgreSQL 18.6),
  and ''::bigint would fail every later write on that pooled connection;
- txid is pg_current_xact_id(), the successor of txid_current(), which the
  PostgreSQL 13+ docs list as deprecated. xid8 has no cast to bigint, text has.
  stmt_at is statement_timestamp(): one value per client statement;
- db_role is session_user, the login. Under SECURITY DEFINER current_user is the
  function owner. db_application is application_name, which any client sets
  (settings set it for the app): a hint, not proof.
- current_query() and the client address are never stored: the query text
  holds the literal values of excluded columns.

audit_row_truncate(label) writes one row with op TRUNCATE and no row_pk, from
an AFTER TRUNCATE statement trigger.

Both are SECURITY DEFINER, so the app role needs no INSERT on audit_rowchange
and cannot forge rows. Following "Writing SECURITY DEFINER Functions Safely"
(PostgreSQL 18 docs, CREATE FUNCTION): search_path pinned with pg_temp last,
every table name schema-qualified, EXECUTE revoked from PUBLIC in the same
transaction, so no other role can attach them to a table of its own (CREATE
TRIGGER needs EXECUTE, firing a trigger does not).
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION audit_row_change() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    pk_columns jsonb := TG_ARGV[1]::jsonb;
    excluded text[] := TG_ARGV[2:];
    full_row jsonb;
    old_row jsonb;
    new_row jsonb;
    old_changed jsonb;
    new_changed jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        full_row := to_jsonb(OLD);
        old_row := full_row - excluded;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        full_row := to_jsonb(NEW);
        new_row := full_row - excluded;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        SELECT jsonb_object_agg(n.key, old_row -> n.key), jsonb_object_agg(n.key, n.value)
          INTO old_changed, new_changed
          FROM jsonb_each(new_row) AS n
         WHERE n.value IS DISTINCT FROM old_row -> n.key;
        IF new_changed IS NULL THEN
            RETURN NULL;
        END IF;
        old_row := old_changed;
        new_row := new_changed;
    END IF;
    INSERT INTO public.audit_rowchange
        (occurred_at, stmt_at, txid, table_label, row_pk, op, old, new,
         actor_id, request_id, db_role, db_application)
    VALUES (
        transaction_timestamp(),
        statement_timestamp(),
        pg_current_xact_id()::text::bigint,
        TG_ARGV[0],
        CASE WHEN jsonb_array_length(pk_columns) = 1
            THEN full_row ->> (pk_columns ->> 0)
            ELSE (SELECT jsonb_agg(full_row -> p.name ORDER BY p.position)
                    FROM jsonb_array_elements_text(pk_columns)
                         WITH ORDINALITY AS p(name, position))::text
        END,
        TG_OP,
        old_row,
        new_row,
        NULLIF(current_setting('app.actor_id', true), '')::bigint,
        NULLIF(current_setting('app.request_id', true), ''),
        session_user,
        current_setting('application_name')
    );
    RETURN NULL;
END;
$$;

CREATE FUNCTION audit_row_truncate() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    INSERT INTO public.audit_rowchange
        (occurred_at, stmt_at, txid, table_label, row_pk, op, old, new,
         actor_id, request_id, db_role, db_application)
    VALUES (
        transaction_timestamp(),
        statement_timestamp(),
        pg_current_xact_id()::text::bigint,
        TG_ARGV[0],
        NULL,
        'TRUNCATE',
        NULL,
        NULL,
        NULLIF(current_setting('app.actor_id', true), '')::bigint,
        NULLIF(current_setting('app.request_id', true), ''),
        session_user,
        current_setting('application_name')
    );
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION audit_row_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION audit_row_truncate() FROM PUBLIC;
"""

REVERSE = """
DROP FUNCTION audit_row_truncate();
DROP FUNCTION audit_row_change();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0002_append_only")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
