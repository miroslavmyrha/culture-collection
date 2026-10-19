"""Row audit on the batch, vial and placement tables (every column audited,
audit.registry.ROW_AUDITED_TABLES), and the triggers that hold them against every writer:
QuerySet.update(), raw SQL, psql (ADR 0008, amendment of 2026-10-19).

lineage_batch_guard: a batch is never deleted and changes only its status (the edges come
with the checks, #17).

lineage_vial_guard: a vial is never deleted and keeps its lab, batch, seq and public id. A
new status must follow the old one along an edge of lineage.models.EDGES (tests compare all
81 pairs), entered_in_error only while the status never changed, and a vial leaves for
consumed, destroyed, distributed, entered_in_error or lost only once its placement is
closed.

lineage_placement_guard: on insert, the box is a box of the vial's lab, the position lies
inside the box, and the vial is in a state that has a place. A row changes once, when it is
closed, and is never deleted.

The functions pin their search_path and reach the other tables through TG_TABLE_SCHEMA.
Row triggers do not fire on TRUNCATE, so Django's test flush still works; the runtime role
has no TRUNCATE and no DELETE here (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION lineage_batch_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'batches are never deleted (batch %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'updated_at') IS DISTINCT FROM
       (to_jsonb(OLD) - 'status' - 'updated_at') THEN
        RAISE EXCEPTION 'a batch changes only its status (batch %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION lineage_vial_guard() RETURNS trigger
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

CREATE FUNCTION lineage_placement_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    box_lab bigint;
    box_kind text;
    box_rows integer;
    box_cols integer;
    vial_lab bigint;
    vial_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'placements are history and never deleted (placement %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.removed_at IS NOT NULL
           OR (to_jsonb(NEW) - 'removed_at' - 'removed_by_id' - 'removal_reason' - 'updated_at')
              IS DISTINCT FROM
              (to_jsonb(OLD) - 'removed_at' - 'removed_by_id' - 'removal_reason' - 'updated_at') THEN
            RAISE EXCEPTION 'a placement changes only once, when it is closed (placement %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT lab_id, kind, rows, cols FROM %I.storage_storageunit WHERE id = $1',
        TG_TABLE_SCHEMA) INTO box_lab, box_kind, box_rows, box_cols USING NEW.box_id;
    EXECUTE format('SELECT lab_id, status FROM %I.lineage_vial WHERE id = $1', TG_TABLE_SCHEMA)
        INTO vial_lab, vial_status USING NEW.vial_id;
    IF box_kind IS DISTINCT FROM 'box' THEN
        RAISE EXCEPTION 'vials are placed in boxes only (placement %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF box_lab IS DISTINCT FROM NEW.lab_id OR vial_lab IS DISTINCT FROM NEW.lab_id THEN
        RAISE EXCEPTION 'a vial, its box and its placement are in one lab (placement %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.row > box_rows OR NEW.col > box_cols THEN
        RAISE EXCEPTION 'position %,% is outside the box of % x % (placement %)',
            NEW.row, NEW.col, box_rows, box_cols, NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.removed_at IS NULL
       AND vial_status IN ('consumed', 'destroyed', 'distributed', 'entered_in_error', 'lost') THEN
        RAISE EXCEPTION 'a % vial has no place in a box (placement %)', vial_status, NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION lineage_batch_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION lineage_vial_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION lineage_placement_guard() FROM PUBLIC;

CREATE TRIGGER lineage_batch_guard BEFORE UPDATE OR DELETE ON lineage_batch
    FOR EACH ROW EXECUTE FUNCTION lineage_batch_guard();
CREATE TRIGGER lineage_vial_guard BEFORE UPDATE OR DELETE ON lineage_vial
    FOR EACH ROW EXECUTE FUNCTION lineage_vial_guard();
CREATE TRIGGER lineage_placement_guard BEFORE INSERT OR UPDATE OR DELETE ON lineage_vialplacement
    FOR EACH ROW EXECUTE FUNCTION lineage_placement_guard();
"""

REVERSE = """
DROP TRIGGER lineage_placement_guard ON lineage_vialplacement;
DROP TRIGGER lineage_vial_guard ON lineage_vial;
DROP TRIGGER lineage_batch_guard ON lineage_batch;
DROP FUNCTION lineage_placement_guard();
DROP FUNCTION lineage_vial_guard();
DROP FUNCTION lineage_batch_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("lineage", "0003_batches_vials_placements"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("lineage_batch", label="lineage.batch"),
        attach_row_audit("lineage_vial", label="lineage.vial"),
        attach_row_audit("lineage_vialplacement", label="lineage.vialplacement"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
