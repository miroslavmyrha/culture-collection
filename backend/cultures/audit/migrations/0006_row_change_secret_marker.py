"""audit_row_change() records that a secret column changed, never its value.

Before this migration an excluded column was dropped from every row, and an
UPDATE that changed only excluded columns wrote no row at all: a password
change left no trace. Now a trigger argument "secret:<column>" (see
cultures.audit.operations, `secret=`) marks a secret column:
- INSERT and DELETE rows leave it out, like any excluded column;
- an UPDATE that changes it stores the column with the marker "redacted" as
  its old and new value (registry.SECRET_MARKER), next to the other changed
  columns, so a password change alone writes one UPDATE row without the hash.
Plain exclusions behave as before. The tables attached so far pass no secret
argument, so their rows do not change; users_user switches its password to a
secret in users migration 0003.

CREATE OR REPLACE keeps the owner, the grants (EXECUTE revoked from PUBLIC in
0003) and the triggers. SECURITY DEFINER and the pinned search_path are part of
the definition, so both are stated again. The reverse restores the 0003 body.
"""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION audit_row_change() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    pk_columns jsonb := TG_ARGV[1]::jsonb;
    secret text[] := ARRAY(
        SELECT substr(a, 8) FROM unnest(TG_ARGV[2:]) AS a WHERE left(a, 7) = 'secret:'
    );
    excluded text[] := ARRAY(
        SELECT a FROM unnest(TG_ARGV[2:]) AS a WHERE left(a, 7) <> 'secret:'
    ) || secret;
    old_full jsonb;
    new_full jsonb;
    old_row jsonb;
    new_row jsonb;
    old_changed jsonb;
    new_changed jsonb;
    secret_changed jsonb;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        old_full := to_jsonb(OLD);
        old_row := old_full - excluded;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        new_full := to_jsonb(NEW);
        new_row := new_full - excluded;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        SELECT jsonb_object_agg(n.key, old_row -> n.key), jsonb_object_agg(n.key, n.value)
          INTO old_changed, new_changed
          FROM jsonb_each(new_row) AS n
         WHERE n.value IS DISTINCT FROM old_row -> n.key;
        SELECT jsonb_object_agg(s.name, 'redacted')
          INTO secret_changed
          FROM unnest(secret) AS s(name)
         WHERE new_full -> s.name IS DISTINCT FROM old_full -> s.name;
        IF new_changed IS NULL AND secret_changed IS NULL THEN
            RETURN NULL;
        END IF;
        old_row := coalesce(old_changed, '{}') || coalesce(secret_changed, '{}');
        new_row := coalesce(new_changed, '{}') || coalesce(secret_changed, '{}');
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
            THEN coalesce(new_full, old_full) ->> (pk_columns ->> 0)
            ELSE (SELECT jsonb_agg(coalesce(new_full, old_full) -> p.name ORDER BY p.position)
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
"""

# The body of migration 0003, unchanged.
REVERSE = """
CREATE OR REPLACE FUNCTION audit_row_change() RETURNS trigger
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
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0005_auditevent_lab_time_idx")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
