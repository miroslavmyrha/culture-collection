"""Row audit on lineage_passage (every column audited, audit.registry.ROW_AUDITED_TABLES),
and a guard trigger: a passage is never deleted and never changed, so its source is
written once (ADR 0008, D1). updated_at may change."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION lineage_passage_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'passages are lineage and never deleted (passage %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'a passage never changes (passage %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION lineage_passage_guard() FROM PUBLIC;

CREATE TRIGGER lineage_passage_guard BEFORE UPDATE OR DELETE ON lineage_passage
    FOR EACH ROW EXECUTE FUNCTION lineage_passage_guard();
"""

REVERSE = """
DROP TRIGGER lineage_passage_guard ON lineage_passage;
DROP FUNCTION lineage_passage_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("lineage", "0001_initial"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("lineage_passage", label="lineage.passage"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
