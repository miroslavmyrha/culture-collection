"""Every risk group states what it rests on, against every writer (#169).

Three function bodies replaced on top of migration 0014, and one helper they share:

- strains_risk_group_entry_states: whether a list entry may be named as the basis of a group. It
  is an entry of the current reading of annex 7 of government order 361/2007 Sb. that states
  that very group, and nothing else. `biosafety.selectors.states_risk_group` asks the same in
  Python, and a parity test compares the two.
- The strain guard now asks of every INSERT what it already asked of every change of the group:
  a basis in words and the time it was stated. So a strain enters the collection saying what its
  risk group rests on, which is the half of annex 7 that no list can answer (R-RISK-07: an agent
  the list does not place in groups 2 to 4 is not thereby in group 1). Rows written before this
  are untouched, and no basis is invented for them.
- Where a group rests on a list entry, on the insert and on every change, that entry must state
  it. A lowering must also carry the entry of the proposal it was confirmed from, and the
  deferred check of a confirmed proposal compares the entry beside the group, the basis and the
  time.
- The proposal guard asks the same of a proposal's own entry when it is made.

The messages name the strain or the proposal, never the organism. The functions pin their
search_path, so they reach the list tables and the helper through TG_TABLE_SCHEMA.
"""

from django.db import migrations

FUNCTIONS = r"""
-- #169: the one question the basis of a risk group asks of a list entry. The strain guard and
-- the proposal guard both call it, so neither can read the lists differently from the other.
-- Not revoked from PUBLIC, unlike the trigger functions: a guard calls it as the role that
-- writes the row, and a role that may not execute it could write no strain at all. It answers
-- one question about published law and reads nothing else.
CREATE FUNCTION strains_risk_group_entry_states(schema_name text, entry bigint, grp smallint)
    RETURNS boolean LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    states boolean;
BEGIN
    IF entry IS NULL THEN
        RETURN true;
    END IF;
    EXECUTE format('SELECT l.is_current AND l.code = $3 AND e.risk_group = $2'
        ' FROM %1$I.biosafety_regulatorylistentry e'
        ' JOIN %1$I.biosafety_regulatorylist l ON l.id = e.list_id'
        ' WHERE e.id = $1', schema_name)
        INTO states USING entry, grp, 'cz-361-2007-annex-7';
    RETURN COALESCE(states, false);
END;
$$;

CREATE OR REPLACE FUNCTION strains_riskgroupproposal_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    strain_lab bigint;
    strain_status text;
    strain_group smallint;
    entry_states boolean;
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
    EXECUTE format('SELECT %1$I.strains_risk_group_entry_states($1, $2, $3)', TG_TABLE_SCHEMA)
        INTO entry_states USING TG_TABLE_SCHEMA, NEW.basis_entry_id, NEW.risk_group;
    IF NOT entry_states THEN
        RAISE EXCEPTION 'a proposed risk group rests on an entry of the current annex 7 of government order 361/2007 Sb. that states it (proposal %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION strains_strain_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    regulated boolean;
    quarantine boolean;
    confirmed boolean;
    entry_states boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status = 'deaccessioned' THEN
            RAISE EXCEPTION 'a strain enters the collection before it leaves it (strain %)', NEW.public_id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.risk_group_basis !~ '\S' OR NEW.risk_group_set_at IS NULL THEN
            RAISE EXCEPTION 'a strain states what its risk group rests on and when (strain %)', NEW.public_id
                USING ERRCODE = 'check_violation';
        END IF;
        EXECUTE format('SELECT %1$I.strains_risk_group_entry_states($1, $2, $3)', TG_TABLE_SCHEMA)
            INTO entry_states USING TG_TABLE_SCHEMA, NEW.risk_group_entry_id, NEW.risk_group;
        IF NOT entry_states THEN
            RAISE EXCEPTION 'a risk group rests on an entry of the current annex 7 of government order 361/2007 Sb. that states it (strain %)',
                NEW.public_id USING ERRCODE = 'check_violation';
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
        EXECUTE format('SELECT %1$I.strains_risk_group_entry_states($1, $2, $3)', TG_TABLE_SCHEMA)
            INTO entry_states USING TG_TABLE_SCHEMA, NEW.risk_group_entry_id, NEW.risk_group;
        IF NOT entry_states THEN
            RAISE EXCEPTION 'a risk group rests on an entry of the current annex 7 of government order 361/2007 Sb. that states it (strain %)',
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
                ' AND from_risk_group = $4 AND basis = $5'
                ' AND basis_entry_id IS NOT DISTINCT FROM $6)', TG_TABLE_SCHEMA)
                INTO confirmed USING OLD.id, NEW.risk_group_set_at, NEW.risk_group,
                    OLD.risk_group, NEW.risk_group_basis, NEW.risk_group_entry_id;
            IF NOT confirmed THEN
                RAISE EXCEPTION 'a lower risk group is set only when a second person confirms a proposal to lower it (strain %)',
                    OLD.public_id USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    ELSIF NEW.risk_group_basis IS DISTINCT FROM OLD.risk_group_basis
          OR NEW.risk_group_set_at IS DISTINCT FROM OLD.risk_group_set_at
          OR NEW.risk_group_entry_id IS DISTINCT FROM OLD.risk_group_entry_id THEN
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

CREATE OR REPLACE FUNCTION strains_riskgroupproposal_confirmed() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    held boolean;
BEGIN
    -- The rows as committed now, not as this queued event saw them.
    EXECUTE format('SELECT p.confirmed_at IS NULL OR EXISTS (SELECT FROM %1$I.strains_strain s'
        ' WHERE s.id = p.strain_id AND ((s.risk_group = p.risk_group'
        ' AND s.risk_group_basis = p.basis AND s.risk_group_set_at = p.confirmed_at'
        ' AND s.risk_group_entry_id IS NOT DISTINCT FROM p.basis_entry_id)'
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
"""

# The bodies of migration 0014, for the reverse.
REVERSE = r"""CREATE OR REPLACE FUNCTION strains_riskgroupproposal_guard() RETURNS trigger
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

CREATE OR REPLACE FUNCTION strains_riskgroupproposal_confirmed() RETURNS trigger
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

DROP FUNCTION strains_risk_group_entry_states(text, bigint, smallint);
"""


class Migration(migrations.Migration):
    dependencies = [("strains", "0017_risk_group_basis")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
