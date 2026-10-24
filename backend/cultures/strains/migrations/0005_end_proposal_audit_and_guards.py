"""Row audit and triggers of the two-person end of a restriction (#105), against every writer:
QuerySet.update(), raw SQL, psql (ADR 0009, amendment of 2026-10-24).

- strains_restrictionendproposal: never deleted; inserted open, for an active restriction of its
  lab; the one update is its confirmation or its withdrawal, once, and nothing else of it
  changes. The proposer never confirms it (also a check constraint).
- The restriction guard (from 0003) adds: a restriction ends only at the confirmation of a
  proposal to end it, at that time and with its reason. A restriction ended before #105 keeps
  its end as it was.

Restrictions existing before #105 need nothing: the guard asks for a proposal only when a
restriction ends from now on. The functions pin their search_path and reach other tables
through TG_TABLE_SCHEMA. The runtime role has SELECT, INSERT and UPDATE on the proposals
(audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION strains_endproposal_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    restriction_lab bigint;
    restriction_ended timestamptz;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a proposal to end a restriction is never deleted: withdraw it (proposal %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.confirmed_at IS NOT NULL OR OLD.withdrawn_at IS NOT NULL
           OR (to_jsonb(NEW) - 'confirmed_at' - 'confirmed_by_id' - 'withdrawn_at'
                   - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at')
              IS DISTINCT FROM
              (to_jsonb(OLD) - 'confirmed_at' - 'confirmed_by_id' - 'withdrawn_at'
                   - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at') THEN
            RAISE EXCEPTION 'a proposal to end a restriction changes once, when it is confirmed or withdrawn (proposal %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT lab_id, ended_at FROM %I.strains_strainrestriction WHERE id = $1',
        TG_TABLE_SCHEMA) INTO restriction_lab, restriction_ended USING NEW.restriction_id;
    IF restriction_lab IS DISTINCT FROM NEW.lab_id OR restriction_ended IS NOT NULL
       OR NEW.confirmed_at IS NOT NULL OR NEW.withdrawn_at IS NOT NULL THEN
        RAISE EXCEPTION 'a proposal is made open, to end an active restriction of its lab (proposal %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- From 0003, with the end of a restriction only at the confirmation of a proposal.
CREATE OR REPLACE FUNCTION strains_restriction_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    confirmed boolean;
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
    IF OLD.ended_at IS NULL AND NEW.ended_at IS NOT NULL THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.strains_restrictionendproposal'
            ' WHERE restriction_id = $1 AND confirmed_at = $2 AND reason = $3)', TG_TABLE_SCHEMA)
            INTO confirmed USING OLD.id, NEW.ended_at, NEW.end_reason;
        IF NOT confirmed THEN
            RAISE EXCEPTION 'a restriction ends only when a second person confirms a proposal to end it (restriction %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION strains_endproposal_guard() FROM PUBLIC;

CREATE TRIGGER strains_endproposal_guard
    BEFORE INSERT OR UPDATE OR DELETE ON strains_restrictionendproposal
    FOR EACH ROW EXECUTE FUNCTION strains_endproposal_guard();
"""

# The guard of 0003 as it was, for the reverse.
RESTRICTION_GUARD_0003 = r"""
CREATE OR REPLACE FUNCTION strains_restriction_guard() RETURNS trigger
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
"""

REVERSE = (
    """
DROP TRIGGER strains_endproposal_guard ON strains_restrictionendproposal;
DROP FUNCTION strains_endproposal_guard();
"""
    + RESTRICTION_GUARD_0003
)


class Migration(migrations.Migration):
    dependencies = [("strains", "0004_restrictionendproposal")]

    operations = [
        attach_row_audit("strains_restrictionendproposal", label="strains.restrictionendproposal"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
