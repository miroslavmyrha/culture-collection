"""A confirmed proposal holds what it confirmed (#151, ADR 0009, amendment of 2026-10-31).

0005 and 0009 hold one direction: a restriction ends, and a regulated strain is deaccessioned,
only at the confirmation of a proposal. These deferred constraint triggers hold the other one,
at commit, against every writer:

- strains_straindeaccessionproposal: a confirmed proposal has its strain deaccessioned at the
  confirmation's time, by the confirmer, with the proposal's cause, reason and final use.
- strains_restrictionendproposal: a confirmed proposal has its restriction ended at the
  confirmation's time with the proposal's reason.

The services write the confirmation before the strain or the restriction (the guards of 0005
and 0009 ask for it), so these checks wait for the commit; the services set them deferred, also
in a session that set its constraints immediate. A constraint trigger fires only for rows written
after it exists. The functions pin their search_path and reach other tables through
TG_TABLE_SCHEMA.
"""

from django.db import migrations

FUNCTIONS = r"""
CREATE FUNCTION strains_deaccessionproposal_confirmed() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    held boolean;
BEGIN
    -- The rows as committed now, not as this queued event saw them.
    EXECUTE format('SELECT p.confirmed_at IS NULL OR EXISTS (SELECT FROM %1$I.strains_strain s'
        ' WHERE s.id = p.strain_id AND s.status = ''deaccessioned'''
        ' AND s.deaccessioned_at = p.confirmed_at AND s.deaccessioned_by_id = p.confirmed_by_id'
        ' AND s.deaccession_cause = p.cause AND s.deaccession_reason = p.reason'
        ' AND s.final_use = p.final_use)'
        ' FROM %1$I.strains_straindeaccessionproposal p WHERE p.id = $1', TG_TABLE_SCHEMA)
        INTO held USING NEW.id;
    IF NOT held THEN
        RAISE EXCEPTION 'a confirmed proposal deaccessions its strain at the confirmation, by the confirmer, with its cause, reason and final use (proposal %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION strains_endproposal_confirmed() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    held boolean;
BEGIN
    -- The rows as committed now, not as this queued event saw them.
    EXECUTE format('SELECT p.confirmed_at IS NULL OR EXISTS (SELECT FROM %1$I.strains_strainrestriction r'
        ' WHERE r.id = p.restriction_id AND r.ended_at = p.confirmed_at AND r.end_reason = p.reason)'
        ' FROM %1$I.strains_restrictionendproposal p WHERE p.id = $1', TG_TABLE_SCHEMA)
        INTO held USING NEW.id;
    IF NOT held THEN
        RAISE EXCEPTION 'a confirmed proposal ends its restriction at the confirmation, with its reason (proposal %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION strains_deaccessionproposal_confirmed() FROM PUBLIC;
REVOKE ALL ON FUNCTION strains_endproposal_confirmed() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER strains_deaccessionproposal_confirmed
    AFTER INSERT OR UPDATE ON strains_straindeaccessionproposal DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION strains_deaccessionproposal_confirmed();
CREATE CONSTRAINT TRIGGER strains_endproposal_confirmed
    AFTER INSERT OR UPDATE ON strains_restrictionendproposal DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION strains_endproposal_confirmed();
"""

REVERSE = """
DROP TRIGGER strains_endproposal_confirmed ON strains_restrictionendproposal;
DROP TRIGGER strains_deaccessionproposal_confirmed ON strains_straindeaccessionproposal;
DROP FUNCTION strains_endproposal_confirmed();
DROP FUNCTION strains_deaccessionproposal_confirmed();
"""


class Migration(migrations.Migration):
    dependencies = [("strains", "0009_deaccession_audit_and_guards")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
