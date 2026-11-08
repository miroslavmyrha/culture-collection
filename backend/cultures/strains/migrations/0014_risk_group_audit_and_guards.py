"""Row audit and triggers of the two-person lowering of a risk group (#174), against every
writer: QuerySet.update(), raw SQL, psql (ADR 0009, amendment of 2026-11-04).

- strains_riskgroupproposal: never deleted; inserted open, to lower the group a strain of its
  lab has now; the one update is its confirmation or its withdrawal, once, and nothing else of
  it changes. The proposer never confirms it (also a check constraint).
- The strain guard (from 0009) adds, for every change of risk_group: the change states its
  basis and the time it was made, and that time is later than the last change's, so a confirmed
  proposal is applied once and never replayed; a raise goes one step at a time; a lower group is
  set only at the confirmation of a proposal to lower it from that group to this one with that
  basis, at that time. The basis and the time change only with the group.
- strains_riskgroupproposal_confirmed, deferred to the commit as strains 0010 does for the other
  two proposals: a confirmed proposal has its strain at that group with that basis at the
  confirmation's time, or the strain has been changed again since (its risk_group_set_at is
  later). A risk group changes again and again, unlike a deaccession, and several changes may
  share one transaction, so the check reads "was applied at its time, unless a later change
  moved on" rather than "is the strain's state now".

The guard asks nothing of a strain whose group never changes, and nothing of the group the
accession recorded: no row needs a basis after the fact. The confirmer is not written on the
strain (the audit event names the actor, the proposal both people), so the guard pins the
lowering by the strain, both groups, the basis and the confirmation's time.

The functions pin their search_path and reach other tables through TG_TABLE_SCHEMA. The runtime
role has SELECT, INSERT and UPDATE on the proposals (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION strains_riskgroupproposal_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    strain_lab bigint;
    strain_status text;
    strain_group smallint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a proposal to lower a risk group is never deleted: withdraw it (proposal %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.confirmed_at IS NOT NULL OR OLD.withdrawn_at IS NOT NULL
           OR (to_jsonb(NEW) - 'confirmed_at' - 'confirmed_by_id' - 'withdrawn_at'
                   - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at')
              IS DISTINCT FROM
              (to_jsonb(OLD) - 'confirmed_at' - 'confirmed_by_id' - 'withdrawn_at'
                   - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at') THEN
            RAISE EXCEPTION 'a proposal to lower a risk group changes once, when it is confirmed or withdrawn (proposal %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT lab_id, status, risk_group FROM %I.strains_strain WHERE id = $1',
        TG_TABLE_SCHEMA) INTO strain_lab, strain_status, strain_group USING NEW.strain_id;
    IF strain_lab IS DISTINCT FROM NEW.lab_id OR strain_status NOT IN ('active', 'restricted')
       OR NEW.from_risk_group IS DISTINCT FROM strain_group
       OR NEW.confirmed_at IS NOT NULL OR NEW.withdrawn_at IS NOT NULL THEN
        RAISE EXCEPTION 'a proposal is made open, to lower the risk group a strain of its lab in the collection has now (proposal %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- From 0009, with the risk group's basis and the two people a lower group takes.
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
    IF NEW.risk_group IS DISTINCT FROM OLD.risk_group THEN
        IF NEW.risk_group_basis !~ '\S' OR NEW.risk_group_set_at IS NULL THEN
            RAISE EXCEPTION 'a risk group change states its basis and the time it was made (strain %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.risk_group_set_at IS NOT NULL AND NEW.risk_group_set_at <= OLD.risk_group_set_at THEN
            RAISE EXCEPTION 'a risk group change is later than the one before it (strain %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.risk_group > OLD.risk_group + 1 THEN
            RAISE EXCEPTION 'a risk group rises one step at a time (strain %)', OLD.public_id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.risk_group < OLD.risk_group THEN
            EXECUTE format('SELECT EXISTS (SELECT FROM %I.strains_riskgroupproposal'
                ' WHERE strain_id = $1 AND confirmed_at = $2 AND risk_group = $3'
                ' AND from_risk_group = $4 AND basis = $5)', TG_TABLE_SCHEMA)
                INTO confirmed USING OLD.id, NEW.risk_group_set_at, NEW.risk_group,
                    OLD.risk_group, NEW.risk_group_basis;
            IF NOT confirmed THEN
                RAISE EXCEPTION 'a lower risk group is set only when a second person confirms a proposal to lower it (strain %)',
                    OLD.public_id USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    ELSIF NEW.risk_group_basis IS DISTINCT FROM OLD.risk_group_basis
          OR NEW.risk_group_set_at IS DISTINCT FROM OLD.risk_group_set_at THEN
        RAISE EXCEPTION 'the basis of a risk group changes with the group (strain %)', OLD.public_id
            USING ERRCODE = 'check_violation';
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

CREATE FUNCTION strains_riskgroupproposal_confirmed() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    held boolean;
BEGIN
    -- The rows as committed now, not as this queued event saw them.
    EXECUTE format('SELECT p.confirmed_at IS NULL OR EXISTS (SELECT FROM %1$I.strains_strain s'
        ' WHERE s.id = p.strain_id AND ((s.risk_group = p.risk_group'
        ' AND s.risk_group_basis = p.basis AND s.risk_group_set_at = p.confirmed_at)'
        ' OR s.risk_group_set_at > p.confirmed_at))'
        ' FROM %1$I.strains_riskgroupproposal p WHERE p.id = $1', TG_TABLE_SCHEMA)
        INTO held USING NEW.id;
    IF NOT held THEN
        RAISE EXCEPTION 'a confirmed proposal lowers its strain to that group at the confirmation, with its basis (proposal %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION strains_riskgroupproposal_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION strains_riskgroupproposal_confirmed() FROM PUBLIC;

CREATE TRIGGER strains_riskgroupproposal_guard
    BEFORE INSERT OR UPDATE OR DELETE ON strains_riskgroupproposal
    FOR EACH ROW EXECUTE FUNCTION strains_riskgroupproposal_guard();

CREATE CONSTRAINT TRIGGER strains_riskgroupproposal_confirmed
    AFTER INSERT OR UPDATE ON strains_riskgroupproposal DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION strains_riskgroupproposal_confirmed();
"""

# The guard of 0009 as it was, for the reverse.
STRAIN_GUARD_0009 = r"""
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
"""

REVERSE = (
    """
DROP TRIGGER strains_riskgroupproposal_confirmed ON strains_riskgroupproposal;
DROP TRIGGER strains_riskgroupproposal_guard ON strains_riskgroupproposal;
DROP FUNCTION strains_riskgroupproposal_confirmed();
DROP FUNCTION strains_riskgroupproposal_guard();
"""
    + STRAIN_GUARD_0009
)


class Migration(migrations.Migration):
    dependencies = [("strains", "0013_one_open_risk_group_proposal")]

    operations = [
        attach_row_audit("strains_riskgroupproposal", label="strains.riskgroupproposal"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
