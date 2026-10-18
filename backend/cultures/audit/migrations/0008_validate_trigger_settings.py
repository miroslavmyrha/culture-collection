"""The row trigger treats app.actor_id and app.request_id as claims and never fails on them.

Any session can set_config both settings (psql, a script), so they are not
proof of who wrote a row (ADR 0005). Before this migration a value that was
not a bigint ('not-a-number', or 19 digits above the bigint range) or a
request id over 64 characters made every write on a regulated table fail in
that session. Now:
- actor_id is kept only when the setting is 1 to 19 ASCII digits within the
  bigint range. [0-9], not \\d: the regex digit class follows the locale and
  could let a non-ASCII digit through to a failing cast. The checks are nested
  IFs because SQL does not promise to evaluate AND from left to right, and the
  cast must never see a value the regex refused;
- otherwise actor_id is null and actor_claim_invalid is true, so
  `audit_reconcile` reports it;
- request_id is cut to 64 characters with left().

Only these values change. audit_row_change() starts from the 0006 body (the
secret marker of #33) and audit_row_truncate() from 0003, the last migrations
that replaced them. The changed lines are marked "#34" in FORWARD. CREATE OR
REPLACE keeps the owner and the ACL, so EXECUTE stays revoked from PUBLIC;
SECURITY DEFINER and the search_path are restated because CREATE OR REPLACE
replaces every attribute. REVERSE is the previous text of both functions
(0006 and 0003), restored before the column goes. Another migration that replaces these
functions must start from FORWARD here, keep the #34 lines, and use FORWARD as
its REVERSE.
"""

from django.db import migrations, models

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

CREATE OR REPLACE FUNCTION audit_row_truncate() RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    actor_claim text := NULLIF(current_setting('app.actor_id', true), '');  -- #34
    claimed_actor bigint;  -- #34
BEGIN
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
        NULL,
        'TRUNCATE',
        NULL,
        NULL,
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

# The bodies before this migration: audit_row_change() from 0006_row_change_secret_marker,
# audit_row_truncate() from 0003_row_change_function, both unchanged.
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

CREATE OR REPLACE FUNCTION audit_row_truncate() RETURNS trigger
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
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0007_auditevent_reason_required_user_privileges")]

    operations = [
        migrations.AddField(
            model_name="rowchange",
            name="actor_claim_invalid",
            field=models.BooleanField(db_default=False),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
