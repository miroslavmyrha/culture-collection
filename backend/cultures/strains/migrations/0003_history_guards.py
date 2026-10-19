"""Triggers that hold what the services promise, against every writer: QuerySet.update(),
raw SQL, psql (ADR 0008, D2 and D4).

- strains_strain: never deleted (a number is never given to another strain), and its
  public id, its lab, its name as received and, once set, its accession number and sequence never change.
- strains_strainidentification: never deleted; a row changes only by giving up is_current.
- strains_strainrestriction: never deleted; a row changes only by ending, once.
updated_at may change with any allowed write. Row triggers do not fire on TRUNCATE, so
Django's test flush still works; the runtime role has no TRUNCATE (audit.roles).
The functions are owned by the migration role and pin their search_path.
"""

from django.db import migrations

FUNCTIONS = r"""
CREATE FUNCTION strains_strain_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'strains are never deleted (strain %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'a strain keeps its public id (strain %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.lab_id IS DISTINCT FROM OLD.lab_id THEN
        RAISE EXCEPTION 'a strain stays in its lab (strain %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.name_as_received IS DISTINCT FROM OLD.name_as_received THEN
        RAISE EXCEPTION 'the name as received never changes (strain %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.accession_number IS NOT NULL AND NEW.accession_number IS DISTINCT FROM OLD.accession_number
       OR OLD.accession_seq IS NOT NULL AND NEW.accession_seq IS DISTINCT FROM OLD.accession_seq THEN
        RAISE EXCEPTION 'an accession number never changes (strain %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION strains_identification_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'identifications are history and never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'is_current' - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'is_current' - 'updated_at')
       OR NEW.is_current AND NOT OLD.is_current THEN
        RAISE EXCEPTION 'an identification only stops being current'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION strains_restriction_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'restrictions are history and never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'ended_at' - 'end_reason' - 'updated_at')
           IS DISTINCT FROM (to_jsonb(OLD) - 'ended_at' - 'end_reason' - 'updated_at')
       OR OLD.ended_at IS NOT NULL
          AND (NEW.ended_at IS DISTINCT FROM OLD.ended_at OR NEW.end_reason IS DISTINCT FROM OLD.end_reason) THEN
        RAISE EXCEPTION 'a restriction only ends, once'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION strains_strain_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION strains_identification_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION strains_restriction_guard() FROM PUBLIC;

CREATE TRIGGER strains_strain_guard BEFORE UPDATE OR DELETE ON strains_strain
    FOR EACH ROW EXECUTE FUNCTION strains_strain_guard();
CREATE TRIGGER strains_identification_guard BEFORE UPDATE OR DELETE ON strains_strainidentification
    FOR EACH ROW EXECUTE FUNCTION strains_identification_guard();
CREATE TRIGGER strains_restriction_guard BEFORE UPDATE OR DELETE ON strains_strainrestriction
    FOR EACH ROW EXECUTE FUNCTION strains_restriction_guard();
"""

REVERSE = """
DROP TRIGGER strains_restriction_guard ON strains_strainrestriction;
DROP TRIGGER strains_identification_guard ON strains_strainidentification;
DROP TRIGGER strains_strain_guard ON strains_strain;
DROP FUNCTION strains_restriction_guard();
DROP FUNCTION strains_identification_guard();
DROP FUNCTION strains_strain_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("strains", "0002_row_audit")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
