"""The vial guard of a strain deaccessioned with its material destroyed (#150, ADR 0008
amendment of 2026-10-31), against every writer: QuerySet.update(), raw SQL, psql.

lineage_vial_guard, replaced (its body before this is in migration 0004, the reverse below):
as before, and when the vial's strain is deaccessioned with a final use other than collection
or storage (lineage.models.material_destroyed), the vial takes no state the collection holds for
use (available, reserved, quarantined), and a lost vial goes to to_destroy, an edge no other
vial has. tests/test_vial_states.py tries all 81 pairs for each kind of strain against
lineage.models.vial_edges.

The strain is read through the batch: a deaccession holds the lab lock, as every vial service
does (strains.services.strain_deaccession), and marks the vials before the strain's status
changes (strains.services._leave), so the vials it marks pass the old edges.
"""

from django.db import migrations

FUNCTIONS = r"""
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

REVERSE = r"""
CREATE OR REPLACE FUNCTION lineage_vial_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    placed boolean;
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
    IF NOT (
        OLD.status = 'available' AND NEW.status IN
            ('reserved', 'consumed', 'quarantined', 'to_destroy', 'lost', 'entered_in_error')
        OR OLD.status = 'reserved' AND NEW.status IN ('available', 'distributed', 'to_destroy')
        OR OLD.status = 'quarantined' AND NEW.status IN ('available', 'to_destroy')
        OR OLD.status = 'to_destroy' AND NEW.status = 'destroyed'
        OR OLD.status = 'lost' AND NEW.status = 'available'
    ) THEN
        RAISE EXCEPTION 'a vial cannot go from % to % (vial %)', OLD.status, NEW.status,
            OLD.public_id USING ERRCODE = 'check_violation';
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
    dependencies = [
        ("lineage", "0008_passage_growth_medium_idx"),
        ("strains", "0008_deaccession"),
    ]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
