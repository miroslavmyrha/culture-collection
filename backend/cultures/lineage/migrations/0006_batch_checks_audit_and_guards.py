"""Row audit on the check table (every column audited, audit.registry.ROW_AUDITED_TABLES), and
the triggers that hold checks and the batch status against every writer: QuerySet.update(),
raw SQL, psql (ADR 0008, amendment of 2026-10-20, #17).

lineage_batch_guard, replaced (its body before this is in migration 0004): a batch is never
deleted and changes only its status, the reason for it and when it changed. A new status must
follow the old one along an edge of lineage.models.BATCH_EDGES (tests compare all 16 pairs),
and a batch is released only while the latest valid identity, purity and viability checks
each passed or were reduced.

lineage_batchcheck_guard: on insert, a check is valid, in the lab of its batch, not dated
before the batch was preserved, and its vial and the row it supersedes belong to the same
batch (the row it supersedes also to the same kind). A row changes once, from valid to entered
in error with a reason, and is never deleted.

The functions pin their search_path and reach the other tables through TG_TABLE_SCHEMA. Row
triggers do not fire on TRUNCATE, so Django's test flush still works; the runtime role has no
TRUNCATE and no DELETE here (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION lineage_batch_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    unpassed text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'batches are never deleted (batch %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'status_reason' - 'status_changed_at' - 'updated_at')
       IS DISTINCT FROM
       (to_jsonb(OLD) - 'status' - 'status_reason' - 'status_changed_at' - 'updated_at') THEN
        RAISE EXCEPTION 'a batch changes only its status (batch %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
    END IF;
    IF NOT (
        OLD.status = 'pending_check' AND NEW.status IN ('released', 'on_hold', 'exhausted')
        OR OLD.status = 'released' AND NEW.status IN ('on_hold', 'pending_check', 'exhausted')
        OR OLD.status = 'on_hold' AND NEW.status IN ('released', 'exhausted')
    ) THEN
        RAISE EXCEPTION 'a batch cannot go from % to % (batch %)', OLD.status, NEW.status,
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'released' THEN
        -- The kinds whose latest valid check is missing or failed.
        EXECUTE format(
            'SELECT string_agg(k.kind, '', '' ORDER BY k.kind)'
            ' FROM (VALUES (''identity''), (''purity''), (''viability'')) AS k(kind)'
            ' LEFT JOIN LATERAL (SELECT c.result FROM %I.lineage_batchcheck c'
            '   WHERE c.batch_id = $1 AND c.kind = k.kind AND c.status = ''valid'''
            '   ORDER BY c.checked_on DESC, c.id DESC LIMIT 1) AS latest ON true'
            ' WHERE latest.result IS NULL OR latest.result NOT IN (''pass'', ''reduced'')',
            TG_TABLE_SCHEMA) INTO unpassed USING OLD.id;
        IF unpassed IS NOT NULL THEN
            RAISE EXCEPTION 'a batch is released only after passed checks, not of % (batch %)',
                unpassed, OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION lineage_batchcheck_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    batch_lab bigint;
    batch_preserved date;
    other_batch bigint;
    other_kind text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'checks are history and never deleted (check %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status <> 'valid' OR NEW.status <> 'entered_in_error'
           OR (to_jsonb(NEW) - 'status' - 'reason' - 'updated_at')
              IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'reason' - 'updated_at') THEN
            RAISE EXCEPTION 'a check changes only once, when it is entered in error (check %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.status <> 'valid' THEN
        RAISE EXCEPTION 'a check is recorded valid (check %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    EXECUTE format('SELECT lab_id, preserved_on FROM %I.lineage_batch WHERE id = $1',
        TG_TABLE_SCHEMA) INTO batch_lab, batch_preserved USING NEW.batch_id;
    IF batch_lab IS DISTINCT FROM NEW.lab_id THEN
        RAISE EXCEPTION 'a check is in the lab of its batch (check %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.checked_on < batch_preserved THEN
        RAISE EXCEPTION 'a check is not dated before its batch was preserved (check %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.vial_id IS NOT NULL THEN
        EXECUTE format('SELECT batch_id FROM %I.lineage_vial WHERE id = $1', TG_TABLE_SCHEMA)
            INTO other_batch USING NEW.vial_id;
        IF other_batch IS DISTINCT FROM NEW.batch_id THEN
            RAISE EXCEPTION 'the vial of a check belongs to its batch (check %)', NEW.public_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF NEW.supersedes_id IS NOT NULL THEN
        EXECUTE format('SELECT batch_id, kind FROM %I.lineage_batchcheck WHERE id = $1',
            TG_TABLE_SCHEMA) INTO other_batch, other_kind USING NEW.supersedes_id;
        IF other_batch IS DISTINCT FROM NEW.batch_id OR other_kind IS DISTINCT FROM NEW.kind THEN
            RAISE EXCEPTION 'a check supersedes a check of the same batch and kind (check %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION lineage_batch_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION lineage_batchcheck_guard() FROM PUBLIC;

CREATE TRIGGER lineage_batchcheck_guard BEFORE INSERT OR UPDATE OR DELETE ON lineage_batchcheck
    FOR EACH ROW EXECUTE FUNCTION lineage_batchcheck_guard();
"""

# The batch guard as migration 0004 left it: a batch changes only its status, any status.
REVERSE = r"""
DROP TRIGGER lineage_batchcheck_guard ON lineage_batchcheck;
DROP FUNCTION lineage_batchcheck_guard();

CREATE OR REPLACE FUNCTION lineage_batch_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'batches are never deleted (batch %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'updated_at') IS DISTINCT FROM
       (to_jsonb(OLD) - 'status' - 'updated_at') THEN
        RAISE EXCEPTION 'a batch changes only its status (batch %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("lineage", "0005_batch_checks"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("lineage_batchcheck", label="lineage.batchcheck"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
