"""The destruction record (#160) against every writer: QuerySet.update(), raw SQL, psql (ADR 0008
and ADR 0009, amendments of 2026-11-03; destruction study s12, decisions of 2026-11-02).

- lineage_destructionrecord: never deleted. Inserted valid and unconfirmed, for a strain of its
  lab. A strain without an active restriction is destroyed at recording (completed_at =
  recorded_at); a regulated one waits for its confirmation (completed_at null) and says how the
  inactivation was verified; a cz_vrat names its witness; a cz_vrat or cz_rat is inactivated in
  the lab before an outside firm takes it; a quarantine_pest names the lab's ÚKZÚZ permit, started by the day of
  the destruction, whose declared method it used, and nothing else names a permit. Its one
  change is the confirmation (once, while it waits; completed_at = confirmed_at, by someone
  other than the recorder: check constraints) or being entered in error (once, with a reason);
  a record entered in error changes no more.
- lineage_destructionvial: never changed or deleted. On insert: the vial is of the record's lab
  and strain, to destroy, and in no other valid record; the record is valid and was written by
  this same transaction (its xmin is in progress, as in distribution 0010), so no vial is added
  to a record later.
- At commit (deferred constraint triggers): a record holds at least one vial; a completed one
  holds only vials destroyed at its completed_at, a valid waiting one only vials to destroy. A
  vial that becomes destroyed has a record completed at that moment, confirmed by a second
  person when its strain is regulated.
- lineage_vial_guard, replaced (its body before this is in migration 0010, the reverse below):
  as before, without 0010's refusal of destroyed for a regulated strain, which the record and
  its confirmation now hold.

"Regulated" is the SQL twin of strains.selectors.regulating_restrictions() (ended_at IS NULL),
and the kinds' rules are written twice: here and in lineage.services.destructions
(Required, _check_rules). tests/test_destruction_guards.py builds each case and asserts that both
agree. The services set the deferred triggers deferred, also in a session that set its
constraints immediate. A constraint trigger fires only for rows written after it exists. The
functions pin their search_path and reach other tables through TG_TABLE_SCHEMA. The runtime role
has SELECT, INSERT and UPDATE on the records and SELECT and INSERT on their vials (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION lineage_destructionrecord_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    strain_lab bigint;
    kinds text[];
    permit_lab bigint;
    permit_kind text;
    permit_method text;
    permit_from date;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a destruction record is never deleted: enter it in error (record %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status <> 'valid'
           OR (to_jsonb(NEW) - 'confirmed_by_id' - 'confirmed_at' - 'completed_at' - 'status'
                   - 'error_reason' - 'entered_in_error_by_id' - 'entered_in_error_at'
                   - 'updated_at')
              IS DISTINCT FROM
              (to_jsonb(OLD) - 'confirmed_by_id' - 'confirmed_at' - 'completed_at' - 'status'
                   - 'error_reason' - 'entered_in_error_by_id' - 'entered_in_error_at'
                   - 'updated_at') THEN
            RAISE EXCEPTION 'a destruction record changes once, when it is confirmed or entered in error (record %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        IF (NEW.confirmed_by_id, NEW.confirmed_at, NEW.completed_at)
           IS DISTINCT FROM (OLD.confirmed_by_id, OLD.confirmed_at, OLD.completed_at)
           AND (OLD.completed_at IS NOT NULL OR NEW.confirmed_at IS NULL OR NEW.status <> 'valid') THEN
            RAISE EXCEPTION 'a destruction record is confirmed once, while it waits for it (record %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT lab_id FROM %I.strains_strain WHERE id = $1', TG_TABLE_SCHEMA)
        INTO strain_lab USING NEW.strain_id;
    IF strain_lab IS DISTINCT FROM NEW.lab_id OR NEW.status <> 'valid'
       OR NEW.confirmed_at IS NOT NULL THEN
        RAISE EXCEPTION 'a destruction record is made valid and unconfirmed, for a strain of its lab (record %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    EXECUTE format('SELECT coalesce(array_agg(DISTINCT kind), ''{}'') FROM %I.strains_strainrestriction'
        ' WHERE strain_id = $1 AND ended_at IS NULL', TG_TABLE_SCHEMA) INTO kinds USING NEW.strain_id;
    IF cardinality(kinds) = 0 THEN
        IF NEW.completed_at IS DISTINCT FROM NEW.recorded_at THEN
            RAISE EXCEPTION 'a strain that is not regulated is destroyed when its record is made (record %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    ELSE
        IF NEW.completed_at IS NOT NULL THEN
            RAISE EXCEPTION 'a regulated strain is destroyed only when a second person confirms its record (record %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.verification = '' THEN
            RAISE EXCEPTION 'a regulated strain''s record says how the inactivation was verified (record %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF 'cz_vrat' = ANY (kinds) THEN
        IF NEW.witness_id IS NULL THEN
            RAISE EXCEPTION 'a VRAT record names the witness of the destruction (record %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF kinds && ARRAY['cz_vrat', 'cz_rat'] AND NEW.contractor <> '' AND NOT NEW.inactivated_in_lab THEN
        RAISE EXCEPTION 'a VRAT or RAT is inactivated in the lab before an outside firm takes it (record %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF 'quarantine_pest' = ANY (kinds) THEN
        EXECUTE format('SELECT lab_id, kind, destruction_method, valid_from'
            ' FROM %I.biosafety_labauthorisation WHERE id = $1', TG_TABLE_SCHEMA)
            INTO permit_lab, permit_kind, permit_method, permit_from USING NEW.authorisation_id;
        IF permit_lab IS DISTINCT FROM NEW.lab_id OR permit_kind IS DISTINCT FROM 'quarantine_pest'
           OR permit_method IS DISTINCT FROM NEW.method OR permit_from > NEW.destroyed_on THEN
            RAISE EXCEPTION 'a quarantine pest is destroyed by the method the lab''s permit declares (record %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.authorisation_id IS NOT NULL THEN
        RAISE EXCEPTION 'only a quarantine pest''s record names a permit (record %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION lineage_destructionvial_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    record_lab bigint;
    record_strain bigint;
    record_status text;
    record_xmin bigint;
    vial_lab bigint;
    vial_strain bigint;
    vial_status text;
    elsewhere boolean;
    current_xid bigint := pg_current_xact_id()::text::bigint;
    candidate bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'the vials of a destruction record never change (vial %)', OLD.vial_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT lab_id, strain_id, status, xmin::text::bigint'
        ' FROM %I.lineage_destructionrecord WHERE id = $1', TG_TABLE_SCHEMA)
        INTO record_lab, record_strain, record_status, record_xmin USING NEW.record_id;
    EXECUTE format('SELECT v.lab_id, b.strain_id, v.status FROM %1$I.lineage_vial v'
        ' JOIN %1$I.lineage_batch b ON b.id = v.batch_id WHERE v.id = $1', TG_TABLE_SCHEMA)
        INTO vial_lab, vial_strain, vial_status USING NEW.vial_id;
    -- xmin is a 32-bit xid: give it the epoch of the current one (distribution 0010).
    candidate := (current_xid >> 32 << 32) + record_xmin;
    IF candidate > current_xid + (1::bigint << 31) THEN
        candidate := candidate - (1::bigint << 32);
    END IF;
    IF record_lab IS DISTINCT FROM NEW.lab_id OR vial_lab IS DISTINCT FROM NEW.lab_id
       OR vial_strain IS DISTINCT FROM record_strain OR vial_status IS DISTINCT FROM 'to_destroy'
       OR record_status IS DISTINCT FROM 'valid'
       OR candidate < 0 OR pg_xact_status(candidate::text::xid8) IS DISTINCT FROM 'in progress' THEN
        RAISE EXCEPTION 'a destruction record takes vials to destroy of its strain and lab, when it is made (vial %)',
            NEW.vial_id USING ERRCODE = 'check_violation';
    END IF;
    EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.lineage_destructionvial d'
        ' JOIN %1$I.lineage_destructionrecord r ON r.id = d.record_id'
        ' WHERE d.vial_id = $1 AND r.status = ''valid'' AND r.id <> $2)', TG_TABLE_SCHEMA)
        INTO elsewhere USING NEW.vial_id, NEW.record_id;
    IF elsewhere THEN
        RAISE EXCEPTION 'a vial is in one valid destruction record (vial %)', NEW.vial_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- At commit: the record and its vials agree.
CREATE FUNCTION lineage_destruction_complete() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    current_status text;
    done timestamptz;
    held bigint;
    destroyed bigint;
    waiting bigint;
BEGIN
    -- The rows as committed now, not as this queued event saw them.
    EXECUTE format('SELECT r.status, r.completed_at, count(v.id),'
        ' count(v.id) FILTER (WHERE v.status = ''destroyed'' AND v.status_changed_at = r.completed_at),'
        ' count(v.id) FILTER (WHERE v.status = ''to_destroy'')'
        ' FROM %1$I.lineage_destructionrecord r'
        ' LEFT JOIN %1$I.lineage_destructionvial d ON d.record_id = r.id'
        ' LEFT JOIN %1$I.lineage_vial v ON v.id = d.vial_id'
        ' WHERE r.id = $1 GROUP BY r.id', TG_TABLE_SCHEMA)
        INTO current_status, done, held, destroyed, waiting USING NEW.id;
    IF held = 0 THEN
        RAISE EXCEPTION 'a destruction record holds at least one vial (record %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF done IS NOT NULL AND destroyed <> held THEN
        RAISE EXCEPTION 'a completed destruction record holds only vials destroyed with it (record %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF done IS NULL AND current_status = 'valid' AND waiting <> held THEN
        RAISE EXCEPTION 'a destruction record that waits for its confirmation holds vials to destroy (record %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

-- At commit: a destroyed vial has its record.
CREATE FUNCTION lineage_vial_destroyed_by_record() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    current_status text;
    changed timestamptz;
    regulated boolean;
    recorded boolean;
BEGIN
    -- The row as committed now, not as this queued event saw it.
    EXECUTE format('SELECT v.status, v.status_changed_at, EXISTS (SELECT FROM %1$I.strains_strainrestriction r'
        ' WHERE r.strain_id = b.strain_id AND r.ended_at IS NULL)'
        ' FROM %1$I.lineage_vial v JOIN %1$I.lineage_batch b ON b.id = v.batch_id WHERE v.id = $1',
        TG_TABLE_SCHEMA) INTO current_status, changed, regulated USING NEW.id;
    IF current_status IS DISTINCT FROM 'destroyed' THEN
        RETURN NULL;
    END IF;
    EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.lineage_destructionvial d'
        ' JOIN %1$I.lineage_destructionrecord r ON r.id = d.record_id'
        ' WHERE d.vial_id = $1 AND r.completed_at = $2'
        ' AND (NOT $3 OR r.confirmed_by_id IS NOT NULL))', TG_TABLE_SCHEMA)
        INTO recorded USING NEW.id, changed, regulated;
    IF NOT recorded THEN
        RAISE EXCEPTION 'a vial is destroyed only with its destruction record, confirmed by a second person for a regulated strain (vial %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION lineage_vial_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    placed boolean;
    destroyed boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'vials are never deleted (vial %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'status_changed_at' - 'barcode' - 'updated_at') IS DISTINCT FROM
       (to_jsonb(OLD) - 'status' - 'status_changed_at' - 'barcode' - 'updated_at') THEN
        RAISE EXCEPTION 'a vial keeps its lab, batch and number (vial %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
    END IF;
    -- The strain was deaccessioned with its material destroyed: every final use but collection
    -- and storage (lineage.models.material_destroyed).
    EXECUTE format('SELECT s.status = ''deaccessioned'' AND s.final_use NOT IN (''collection'', ''storage'')'
        ' FROM %1$I.lineage_batch b JOIN %1$I.strains_strain s ON s.id = b.strain_id'
        ' WHERE b.id = $1', TG_TABLE_SCHEMA) INTO destroyed USING NEW.batch_id;
    -- to_destroy > destroyed only together with a completed destruction record (#160): the
    -- deferred lineage_vial_destroyed_by_record checks it at commit.
    IF NOT (
        OLD.status = 'available' AND NEW.status IN
            ('reserved', 'consumed', 'quarantined', 'to_destroy', 'lost', 'entered_in_error')
        OR OLD.status = 'reserved' AND NEW.status IN ('available', 'distributed', 'to_destroy')
        OR OLD.status = 'quarantined' AND NEW.status IN ('available', 'to_destroy')
        OR OLD.status = 'to_destroy' AND NEW.status = 'destroyed'
        OR OLD.status = 'lost' AND NEW.status = 'available'
        OR destroyed AND OLD.status = 'lost' AND NEW.status = 'to_destroy'
    ) THEN
        RAISE EXCEPTION 'a vial cannot go from % to % (vial %)', OLD.status, NEW.status,
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF destroyed AND NEW.status IN ('available', 'reserved', 'quarantined') THEN
        RAISE EXCEPTION 'the strain was deaccessioned with its material destroyed: vial % goes to destruction, not %',
            OLD.public_id, NEW.status USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'entered_in_error' AND OLD.status_changed_at IS NOT NULL THEN
        RAISE EXCEPTION 'only a vial whose status never changed is entered in error (vial %)',
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IN ('consumed', 'destroyed', 'distributed', 'entered_in_error', 'lost') THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.lineage_vialplacement'
            ' WHERE vial_id = $1 AND removed_at IS NULL)', TG_TABLE_SCHEMA)
            INTO placed USING OLD.id;
        IF placed THEN
            RAISE EXCEPTION 'close the placement before the vial leaves its box (vial %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION lineage_destructionrecord_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION lineage_destructionvial_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION lineage_destruction_complete() FROM PUBLIC;
REVOKE ALL ON FUNCTION lineage_vial_destroyed_by_record() FROM PUBLIC;

CREATE TRIGGER lineage_destructionrecord_guard
    BEFORE INSERT OR UPDATE OR DELETE ON lineage_destructionrecord
    FOR EACH ROW EXECUTE FUNCTION lineage_destructionrecord_guard();
CREATE TRIGGER lineage_destructionvial_guard
    BEFORE INSERT OR UPDATE OR DELETE ON lineage_destructionvial
    FOR EACH ROW EXECUTE FUNCTION lineage_destructionvial_guard();
CREATE CONSTRAINT TRIGGER lineage_destruction_complete
    AFTER INSERT OR UPDATE ON lineage_destructionrecord DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION lineage_destruction_complete();
CREATE CONSTRAINT TRIGGER lineage_vial_destroyed_by_record
    AFTER UPDATE OF status ON lineage_vial DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (NEW.status = 'destroyed' AND OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION lineage_vial_destroyed_by_record();
"""

# lineage_vial_guard as migration 0010 left it, for the reverse.
GUARD_0010 = r"""
CREATE OR REPLACE FUNCTION lineage_vial_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    placed boolean;
    destroyed boolean;
    regulated boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'vials are never deleted (vial %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'status_changed_at' - 'barcode' - 'updated_at') IS DISTINCT FROM
       (to_jsonb(OLD) - 'status' - 'status_changed_at' - 'barcode' - 'updated_at') THEN
        RAISE EXCEPTION 'a vial keeps its lab, batch and number (vial %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
        RETURN NEW;
    END IF;
    -- The strain was deaccessioned with its material destroyed: every final use but collection
    -- and storage (lineage.models.material_destroyed).
    EXECUTE format('SELECT s.status = ''deaccessioned'' AND s.final_use NOT IN (''collection'', ''storage'')'
        ' FROM %1$I.lineage_batch b JOIN %1$I.strains_strain s ON s.id = b.strain_id'
        ' WHERE b.id = $1', TG_TABLE_SCHEMA) INTO destroyed USING NEW.batch_id;
    IF NOT (
        OLD.status = 'available' AND NEW.status IN
            ('reserved', 'consumed', 'quarantined', 'to_destroy', 'lost', 'entered_in_error')
        OR OLD.status = 'reserved' AND NEW.status IN ('available', 'distributed', 'to_destroy')
        OR OLD.status = 'quarantined' AND NEW.status IN ('available', 'to_destroy')
        OR OLD.status = 'to_destroy' AND NEW.status = 'destroyed'
        OR OLD.status = 'lost' AND NEW.status = 'available'
        OR destroyed AND OLD.status = 'lost' AND NEW.status = 'to_destroy'
    ) THEN
        RAISE EXCEPTION 'a vial cannot go from % to % (vial %)', OLD.status, NEW.status,
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    -- ADR 0009: no single account destroys a regulated strain. Until the destruction record
    -- with a second person (#160), a vial of a strain with an active restriction is not
    -- destroyed (lineage.models.vial_edges, strains.selectors.regulating_restrictions).
    IF NEW.status = 'destroyed' THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.lineage_batch b'
            ' JOIN %1$I.strains_strainrestriction r ON r.strain_id = b.strain_id'
            ' WHERE b.id = $1 AND r.ended_at IS NULL)', TG_TABLE_SCHEMA)
            INTO regulated USING NEW.batch_id;
        IF regulated THEN
            RAISE EXCEPTION 'a vial of a regulated strain is destroyed only with a destruction record a second person confirms (vial %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF destroyed AND NEW.status IN ('available', 'reserved', 'quarantined') THEN
        RAISE EXCEPTION 'the strain was deaccessioned with its material destroyed: vial % goes to destruction, not %',
            OLD.public_id, NEW.status USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'entered_in_error' AND OLD.status_changed_at IS NOT NULL THEN
        RAISE EXCEPTION 'only a vial whose status never changed is entered in error (vial %)',
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IN ('consumed', 'destroyed', 'distributed', 'entered_in_error', 'lost') THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.lineage_vialplacement'
            ' WHERE vial_id = $1 AND removed_at IS NULL)', TG_TABLE_SCHEMA)
            INTO placed USING OLD.id;
        IF placed THEN
            RAISE EXCEPTION 'close the placement before the vial leaves its box (vial %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

REVERSE = (
    """
DROP TRIGGER lineage_vial_destroyed_by_record ON lineage_vial;
DROP TRIGGER lineage_destruction_complete ON lineage_destructionrecord;
DROP TRIGGER lineage_destructionvial_guard ON lineage_destructionvial;
DROP TRIGGER lineage_destructionrecord_guard ON lineage_destructionrecord;
DROP FUNCTION lineage_vial_destroyed_by_record();
DROP FUNCTION lineage_destruction_complete();
DROP FUNCTION lineage_destructionvial_guard();
DROP FUNCTION lineage_destructionrecord_guard();
"""
    + GUARD_0010
)


class Migration(migrations.Migration):
    dependencies = [("lineage", "0013_destruction_record")]

    operations = [
        attach_row_audit(
            "lineage_destructionrecord",
            label="lineage.destructionrecord",
            personal=("contractor",),
        ),
        attach_row_audit("lineage_destructionvial", label="lineage.destructionvial"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
