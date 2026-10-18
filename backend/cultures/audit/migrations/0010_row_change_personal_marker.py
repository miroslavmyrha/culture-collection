"""The row trigger stores the marker "personal" for personal columns, never their values.

Before this migration every audited column was stored with its value, so the
users' names, emails and usernames were copied into append-only rows that no
erasure could reach (#37). Now a trigger argument "personal:<column>" (see
cultures.audit.operations, `personal=`) marks a personal column:
- INSERT and DELETE rows store the column with the marker "personal"
  (registry.PERSONAL_MARKER) instead of the value, so the row shows the column
  was there;
- an UPDATE that changes it stores the marker as its old and new value, next
  to the other changed columns, so a rename alone writes one UPDATE row.
Plain exclusions and secrets behave as before. The tables attached so far pass
no personal argument, so their rows do not change; users_user marks its
personal columns in users migration 0006.

audit_row_change() starts from the 0008 body, the last migration that replaced
it, so the claims logic of #34 and the secret marker of #33 stay. The changed
lines are marked "#37". audit_row_truncate() is not touched. CREATE OR REPLACE
keeps the owner, the grants (EXECUTE revoked from PUBLIC) and the triggers;
SECURITY DEFINER and the search_path are restated because CREATE OR REPLACE
replaces every attribute. REVERSE is the 0008 body of audit_row_change(). Another
migration that replaces this function must start from FORWARD here, keep the
#34 and #37 lines, and use FORWARD as its REVERSE.
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
    personal text[] := ARRAY(  -- #37
        SELECT substr(a, 10) FROM unnest(TG_ARGV[2:]) AS a WHERE left(a, 9) = 'personal:'
    );
    excluded text[] := ARRAY(
        SELECT a FROM unnest(TG_ARGV[2:]) AS a
         WHERE left(a, 7) <> 'secret:' AND left(a, 9) <> 'personal:'  -- #37
    ) || secret || personal;  -- #37: personal values are never stored either
    old_full jsonb;
    new_full jsonb;
    old_row jsonb;
    new_row jsonb;
    old_changed jsonb;
    new_changed jsonb;
    secret_changed jsonb;
    personal_marked jsonb;  -- #37
    actor_claim text := NULLIF(current_setting('app.actor_id', true), '');  -- #34
    claimed_actor bigint;  -- #34
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
        -- #37 a changed personal column: the marker as its old and new value.
        SELECT jsonb_object_agg(p.name, 'personal')
          INTO personal_marked
          FROM unnest(personal) AS p(name)
         WHERE new_full -> p.name IS DISTINCT FROM old_full -> p.name;
        IF new_changed IS NULL AND secret_changed IS NULL AND personal_marked IS NULL THEN  -- #37
            RETURN NULL;
        END IF;
        old_row := coalesce(old_changed, '{}') || coalesce(secret_changed, '{}')
                   || coalesce(personal_marked, '{}');  -- #37
        new_row := coalesce(new_changed, '{}') || coalesce(secret_changed, '{}')
                   || coalesce(personal_marked, '{}');  -- #37
    ELSE
        -- #37 INSERT and DELETE: the marker for every personal column of the row.
        SELECT jsonb_object_agg(p.name, 'personal')
          INTO personal_marked
          FROM unnest(personal) AS p(name)
         WHERE coalesce(new_full, old_full) ? p.name;
        IF TG_OP = 'INSERT' THEN
            new_row := new_row || coalesce(personal_marked, '{}');
        ELSE
            old_row := old_row || coalesce(personal_marked, '{}');
        END IF;
        -- #37 end
    END IF;
    -- #34 claim validation: keep app.actor_id only when it is a bigint.
    IF actor_claim ~ '^[0-9]{1,19}$' THEN
        IF actor_claim::numeric <= 9223372036854775807 THEN
            claimed_actor := actor_claim::bigint;
        END IF;
    END IF;
    -- #34 end
    INSERT INTO public.audit_rowchange
        (occurred_at, stmt_at, txid, table_label, row_pk, op, old, new,
         actor_id, actor_claim_invalid, request_id, db_role, db_application)  -- #34: actor_claim_invalid
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
        claimed_actor,  -- #34
        actor_claim IS NOT NULL AND claimed_actor IS NULL,  -- #34
        left(NULLIF(current_setting('app.request_id', true), ''), 64),  -- #34: cut to the column
        session_user,
        current_setting('application_name')
    );
    RETURN NULL;
END;
$$;
"""

# The body before this migration: audit_row_change() from 0008_validate_trigger_settings.
REVERSE = """
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
    actor_claim text := NULLIF(current_setting('app.actor_id', true), '');  -- #34
    claimed_actor bigint;  -- #34
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
    -- #34 claim validation: keep app.actor_id only when it is a bigint.
    IF actor_claim ~ '^[0-9]{1,19}$' THEN
        IF actor_claim::numeric <= 9223372036854775807 THEN
            claimed_actor := actor_claim::bigint;
        END IF;
    END IF;
    -- #34 end
    INSERT INTO public.audit_rowchange
        (occurred_at, stmt_at, txid, table_label, row_pk, op, old, new,
         actor_id, actor_claim_invalid, request_id, db_role, db_application)  -- #34: actor_claim_invalid
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
        claimed_actor,  -- #34
        actor_claim IS NOT NULL AND claimed_actor IS NULL,  -- #34
        left(NULLIF(current_setting('app.request_id', true), ''), 64),  -- #34: cut to the column
        session_user,
        current_setting('application_name')
    );
    RETURN NULL;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0009_reason_required_login_limits_cleared")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
