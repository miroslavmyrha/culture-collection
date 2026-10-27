"""Row audit and triggers of the deaccession (#20), against every writer: QuerySet.update(), raw
SQL, psql (ADR 0008, D8, and ADR 0009, amendments of 2026-10-27).

- strains_straindeaccessionproposal: never deleted; inserted open, for a strain of its lab that
  is in the collection (active or restricted); the one update is its confirmation or its
  withdrawal, once, and nothing else of it changes. The proposer never confirms it (also a
  check constraint).
- The strain guard (from 0003) adds: a strain is inserted in the collection, never deaccessioned;
  only a strain in the collection becomes deaccessioned; a deaccessioned strain stays so, and
  its deaccession never changes; a quarantine pest records its final use, and only a quarantine
  pest does; a regulated strain (an active restriction of any kind) becomes deaccessioned only
  at the confirmation of a proposal to deaccession it, by that confirmer, at that time, with
  its cause, reason and final use. The guard now fires on INSERT too.

"Regulated" here is the SQL twin of strains.selectors.regulating_restrictions() (ended_at IS
NULL); tests/test_deaccession.py builds each case of the Python predicate and asserts the
trigger agrees. The functions pin their search_path and reach other tables through
TG_TABLE_SCHEMA. The runtime role has SELECT, INSERT and UPDATE on the proposals (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION strains_deaccessionproposal_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    strain_lab bigint;
    strain_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a proposal to deaccession a strain is never deleted: withdraw it (proposal %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.confirmed_at IS NOT NULL OR OLD.withdrawn_at IS NOT NULL
           OR (to_jsonb(NEW) - 'confirmed_at' - 'confirmed_by_id' - 'withdrawn_at'
                   - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at')
              IS DISTINCT FROM
              (to_jsonb(OLD) - 'confirmed_at' - 'confirmed_by_id' - 'withdrawn_at'
                   - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at') THEN
            RAISE EXCEPTION 'a proposal to deaccession a strain changes once, when it is confirmed or withdrawn (proposal %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT lab_id, status FROM %I.strains_strain WHERE id = $1', TG_TABLE_SCHEMA)
        INTO strain_lab, strain_status USING NEW.strain_id;
    IF strain_lab IS DISTINCT FROM NEW.lab_id OR strain_status NOT IN ('active', 'restricted')
       OR NEW.confirmed_at IS NOT NULL OR NEW.withdrawn_at IS NOT NULL THEN
        RAISE EXCEPTION 'a proposal is made open, to deaccession a strain of its lab in the collection (proposal %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- From 0003, with the deaccession.
CREATE OR REPLACE FUNCTION strains_strain_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    regulated boolean;
    quarantine boolean;
    confirmed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status = 'deaccessioned' THEN
            RAISE EXCEPTION 'a strain enters the collection before it leaves it (strain %)', NEW.public_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
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
    IF OLD.status = 'deaccessioned' THEN
        IF NEW.status IS DISTINCT FROM OLD.status
           OR NEW.deaccessioned_at IS DISTINCT FROM OLD.deaccessioned_at
           OR NEW.deaccessioned_by_id IS DISTINCT FROM OLD.deaccessioned_by_id
           OR NEW.deaccession_cause IS DISTINCT FROM OLD.deaccession_cause
           OR NEW.deaccession_reason IS DISTINCT FROM OLD.deaccession_reason
           OR NEW.final_use IS DISTINCT FROM OLD.final_use THEN
            RAISE EXCEPTION 'a deaccessioned strain stays deaccessioned, as it was recorded (strain %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.status = 'deaccessioned' THEN
        IF OLD.status NOT IN ('active', 'restricted') THEN
            RAISE EXCEPTION 'only a strain in the collection is deaccessioned (strain %)', OLD.public_id
                USING ERRCODE = 'check_violation';
        END IF;
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.strains_strainrestriction'
            ' WHERE strain_id = $1 AND ended_at IS NULL),'
            ' EXISTS (SELECT FROM %I.strains_strainrestriction'
            ' WHERE strain_id = $1 AND ended_at IS NULL AND kind = ''quarantine_pest'')',
            TG_TABLE_SCHEMA, TG_TABLE_SCHEMA) INTO regulated, quarantine USING OLD.id;
        IF quarantine IS DISTINCT FROM (NEW.final_use <> '') THEN
            RAISE EXCEPTION 'a quarantine pest records its final use when it is deaccessioned, and only a quarantine pest does (strain %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
        IF regulated THEN
            EXECUTE format('SELECT EXISTS (SELECT FROM %I.strains_straindeaccessionproposal'
                ' WHERE strain_id = $1 AND confirmed_at = $2 AND confirmed_by_id = $3'
                ' AND cause = $4 AND reason = $5 AND final_use = $6)', TG_TABLE_SCHEMA)
                INTO confirmed USING OLD.id, NEW.deaccessioned_at, NEW.deaccessioned_by_id,
                    NEW.deaccession_cause, NEW.deaccession_reason, NEW.final_use;
            IF NOT confirmed THEN
                RAISE EXCEPTION 'a regulated strain is deaccessioned only when a second person confirms a proposal to deaccession it (strain %)',
                    OLD.public_id USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION strains_deaccessionproposal_guard() FROM PUBLIC;

CREATE TRIGGER strains_deaccessionproposal_guard
    BEFORE INSERT OR UPDATE OR DELETE ON strains_straindeaccessionproposal
    FOR EACH ROW EXECUTE FUNCTION strains_deaccessionproposal_guard();

DROP TRIGGER strains_strain_guard ON strains_strain;
CREATE TRIGGER strains_strain_guard BEFORE INSERT OR UPDATE OR DELETE ON strains_strain
    FOR EACH ROW EXECUTE FUNCTION strains_strain_guard();
"""

# The guard of 0003 as it was, for the reverse.
STRAIN_GUARD_0003 = r"""
DROP TRIGGER strains_strain_guard ON strains_strain;
CREATE OR REPLACE FUNCTION strains_strain_guard() RETURNS trigger
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
CREATE TRIGGER strains_strain_guard BEFORE UPDATE OR DELETE ON strains_strain
    FOR EACH ROW EXECUTE FUNCTION strains_strain_guard();
"""

REVERSE = (
    """
DROP TRIGGER strains_deaccessionproposal_guard ON strains_straindeaccessionproposal;
DROP FUNCTION strains_deaccessionproposal_guard();
"""
    + STRAIN_GUARD_0003
)


class Migration(migrations.Migration):
    dependencies = [("strains", "0008_deaccession")]

    operations = [
        attach_row_audit(
            "strains_straindeaccessionproposal", label="strains.straindeaccessionproposal"
        ),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
