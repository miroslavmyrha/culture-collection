"""A vial of a regulated strain is not destroyed by one person (#158, ADR 0009: "No single
account can destroy, deaccession or ship a regulated strain"), against every writer:
QuerySet.update(), raw SQL, psql.

lineage_vial_guard, replaced (its body before this is in migration 0009, the reverse below): as
before, and a vial whose strain has an active restriction of any kind does not become destroyed,
until the destruction record with a second person (#160). Marking it to destroy stays allowed,
also at a deaccession (strains.services._leave). "Regulated" is the SQL twin of
strains.selectors.regulating_restrictions() (ended_at IS NULL), as in the strain guard (strains
0009); tests/test_vial_states.py tries all 81 pairs for a regulated strain against
lineage.models.vial_edges, and asserts the trigger agrees with the Python predicate for each
restriction kind and for an ended restriction.

The restrictions are read through the batch. They change under the lab lock (strains.services),
which every vial service holds too.
"""

from django.db import migrations

FUNCTIONS = r"""
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

REVERSE = r"""
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
"""


class Migration(migrations.Migration):
    dependencies = [("lineage", "0009_vial_guard_material_destroyed")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
