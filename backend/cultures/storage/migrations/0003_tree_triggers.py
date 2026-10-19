"""Triggers that hold the storage tree against every writer: QuerySet.update(), raw SQL, psql
(ADR 0008, D14).

storage_unit_path, BEFORE INSERT OR UPDATE: the path is the ids from the root down to the
unit, computed from the parent's path. A unit whose parent changes gets a new path; a path
written by hand is refused. On every insert or move under a parent it takes the lab's
advisory lock first, then reads the parent, and refuses
- a parent that does not exist (foreign keys are checked only at commit),
- a parent in another lab,
- a parent that is the unit itself or below it (a cycle),
- a kind the parent may not hold: a rack in a freezer or a tank, a box in a rack, a freezer
  or a tank, nothing else (storage.models.KIND_SPEC, compared pair by pair in the tests).
A new root takes no lock: nothing else can see or reference it yet.

storage_unit_path_below, AFTER UPDATE OF parent_id: rewrites the path of every unit below a
moved one. Its update runs one trigger level down, where storage_unit_path lets the new paths
through (pg_trigger_depth() > 1); the runtime role cannot create triggers of its own.

The lock: a unit never leaves its lab, so a lab's units are one forest, and one advisory lock
per lab serialises every insert and move in it. A move reads the parent's path only after the
lock, so it sees every move committed before it, and an insert under a unit that is being
moved waits until the cascade has committed. The services take the lab row lock before
either (labs.locks), so for them the advisory lock never waits; it holds for the other writers.

storage_unit_guard, BEFORE UPDATE OR DELETE: units are never deleted, keep their public id,
lab and kind, and a retired unit changes no more, except its path when a unit above it moves.
storage_boxtype_guard: box types are never deleted and keep their size, because boxes copied it.

Row triggers do not fire on TRUNCATE, so Django's test flush still works; the runtime role
has no TRUNCATE (audit.roles). The functions pin their search_path and name the table
through TG_TABLE_SCHEMA and TG_TABLE_NAME.
"""

from django.db import migrations

FUNCTIONS = r"""
CREATE FUNCTION storage_unit_path() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    holder_lab bigint;
    holder_kind text;
    holder_path bigint[];
BEGIN
    IF pg_trigger_depth() > 1 THEN
        RETURN NEW;  -- storage_unit_path_below rewriting the paths under a moved unit
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.parent_id IS NOT DISTINCT FROM OLD.parent_id THEN
        IF NEW.path IS DISTINCT FROM OLD.path THEN
            RAISE EXCEPTION 'the path follows the parent and only the database writes it (unit %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.parent_id IS NULL THEN
        NEW.path := ARRAY[NEW.id];
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('storage_storageunit:' || NEW.lab_id, 0));
    EXECUTE format('SELECT lab_id, kind, path FROM %I.%I WHERE id = $1', TG_TABLE_SCHEMA, TG_TABLE_NAME)
        INTO holder_lab, holder_kind, holder_path USING NEW.parent_id;
    IF holder_path IS NULL THEN
        RAISE EXCEPTION 'storage unit % does not exist', NEW.parent_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF holder_lab <> NEW.lab_id THEN
        RAISE EXCEPTION 'a unit and the unit holding it are in the same lab (unit %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.id = ANY (holder_path) THEN
        RAISE EXCEPTION 'a unit cannot go inside itself or a unit it holds (unit %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NOT (NEW.kind = 'rack' AND holder_kind IN ('freezer', 'ln2_tank')
            OR NEW.kind = 'box' AND holder_kind IN ('freezer', 'ln2_tank', 'rack')) THEN
        RAISE EXCEPTION 'a % cannot hold a % (unit %)', holder_kind, NEW.kind, NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.path := holder_path || NEW.id;
    RETURN NEW;
END;
$$;

CREATE FUNCTION storage_unit_path_below() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NEW.path IS DISTINCT FROM OLD.path THEN
        EXECUTE format(
            'UPDATE %I.%I SET path = $1 || path[cardinality($2) + 1:] '
            'WHERE lab_id = $3 AND path @> ARRAY[$4]::bigint[] AND id <> $4',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
        ) USING NEW.path, OLD.path, NEW.lab_id, NEW.id;
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION storage_unit_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'storage units are never deleted, they are retired (unit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'a unit keeps its public id (unit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.lab_id IS DISTINCT FROM OLD.lab_id THEN
        RAISE EXCEPTION 'a unit stays in its lab (unit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.kind IS DISTINCT FROM OLD.kind THEN
        RAISE EXCEPTION 'a unit keeps its kind (unit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'retired' AND (to_jsonb(NEW) - 'path') IS DISTINCT FROM (to_jsonb(OLD) - 'path') THEN
        RAISE EXCEPTION 'a retired unit changes no more (unit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION storage_boxtype_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'box types are never deleted (box type %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.rows IS DISTINCT FROM OLD.rows OR NEW.cols IS DISTINCT FROM OLD.cols THEN
        RAISE EXCEPTION 'a box type keeps its public id and its size (box type %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION storage_unit_path() FROM PUBLIC;
REVOKE ALL ON FUNCTION storage_unit_path_below() FROM PUBLIC;
REVOKE ALL ON FUNCTION storage_unit_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION storage_boxtype_guard() FROM PUBLIC;

CREATE TRIGGER storage_unit_path BEFORE INSERT OR UPDATE ON storage_storageunit
    FOR EACH ROW EXECUTE FUNCTION storage_unit_path();
CREATE TRIGGER storage_unit_path_below AFTER UPDATE OF parent_id ON storage_storageunit
    FOR EACH ROW EXECUTE FUNCTION storage_unit_path_below();
CREATE TRIGGER storage_unit_guard BEFORE UPDATE OR DELETE ON storage_storageunit
    FOR EACH ROW EXECUTE FUNCTION storage_unit_guard();
CREATE TRIGGER storage_boxtype_guard BEFORE UPDATE OR DELETE ON storage_boxtype
    FOR EACH ROW EXECUTE FUNCTION storage_boxtype_guard();
"""

REVERSE = """
DROP TRIGGER storage_boxtype_guard ON storage_boxtype;
DROP TRIGGER storage_unit_guard ON storage_storageunit;
DROP TRIGGER storage_unit_path_below ON storage_storageunit;
DROP TRIGGER storage_unit_path ON storage_storageunit;
DROP FUNCTION storage_boxtype_guard();
DROP FUNCTION storage_unit_guard();
DROP FUNCTION storage_unit_path_below();
DROP FUNCTION storage_unit_path();
"""


class Migration(migrations.Migration):
    dependencies = [("storage", "0002_row_audit")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
