"""Row audit and triggers on the growth media and the conditions that name them (#79), against
every writer: QuerySet.update(), raw SQL, psql (ADR 0008, amendment of 2026-10-27).

- growth_growthmedium: never deleted; its public id, lab and creation time never change; a
  retired medium never changes again (not renamed, not brought back).
- strains_strain and lineage_passage: a medium they name is a medium of their own lab.
updated_at may change with any allowed write. The functions pin their search_path and reach the
medium through TG_TABLE_SCHEMA. The runtime role has SELECT, INSERT and UPDATE on the media
(audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION growth_growthmedium_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'media are never deleted: retire them (medium %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.lab_id IS DISTINCT FROM OLD.lab_id THEN
        RAISE EXCEPTION 'a medium keeps its public id and lab (medium %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.retired_at IS NOT NULL
       AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'a retired medium never changes (medium %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION growth_medium_lab_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    medium_lab bigint;
BEGIN
    IF NEW.growth_medium_id IS NOT NULL THEN
        EXECUTE format('SELECT lab_id FROM %I.growth_growthmedium WHERE id = $1', TG_TABLE_SCHEMA)
            INTO medium_lab USING NEW.growth_medium_id;
        IF medium_lab IS DISTINCT FROM NEW.lab_id THEN
            RAISE EXCEPTION 'the medium belongs to another lab (% %)', TG_TABLE_NAME, NEW.public_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION growth_growthmedium_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION growth_medium_lab_guard() FROM PUBLIC;

CREATE TRIGGER growth_growthmedium_guard BEFORE UPDATE OR DELETE ON growth_growthmedium
    FOR EACH ROW EXECUTE FUNCTION growth_growthmedium_guard();
CREATE TRIGGER growth_medium_lab_guard BEFORE INSERT OR UPDATE OF growth_medium_id, lab_id ON strains_strain
    FOR EACH ROW EXECUTE FUNCTION growth_medium_lab_guard();
CREATE TRIGGER growth_medium_lab_guard BEFORE INSERT ON lineage_passage
    FOR EACH ROW EXECUTE FUNCTION growth_medium_lab_guard();
"""

REVERSE = """
DROP TRIGGER growth_medium_lab_guard ON lineage_passage;
DROP TRIGGER growth_medium_lab_guard ON strains_strain;
DROP TRIGGER growth_growthmedium_guard ON growth_growthmedium;
DROP FUNCTION growth_medium_lab_guard();
DROP FUNCTION growth_growthmedium_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("growth", "0001_growth_medium"),
        ("strains", "0006_growth_conditions"),
        ("lineage", "0007_passage_growth_conditions"),
        ("audit", "0023_validate_reason_required"),
    ]

    operations = [
        attach_row_audit("growth_growthmedium", label="growth.growthmedium"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
