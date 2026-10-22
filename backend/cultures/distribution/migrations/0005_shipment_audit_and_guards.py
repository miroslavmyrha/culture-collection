"""Row audit and triggers of the shipment (#88), against every writer: QuerySet.update(), raw
SQL, psql (ADR 0008, amendment of 2026-10-22).

- distribution_shipment: frozen; on insert its request is of its lab and approved, and the
  responsible person is a contact of the lab.
- distribution_shipmentvial: frozen; on insert its line is of the shipment's request and the
  vial's reservation for that line is open.
- At commit (deferred constraint trigger): a shipment's request is shipped, every reservation
  of the request ended as shipped, and the shipment holds exactly the reserved vials, each
  distributed.
- The request guard (from 0003) adds approved > shipped, only once a shipment exists. A shipped
  request changes no more.
- The reservation guard (from 0003) ends a reservation as shipped only for a vial a shipment of
  its line holds.
- The vial check at commit (from 0003) adds: a vial is distributed only when a shipment holds it.

The functions pin their search_path and reach other tables through TG_TABLE_SCHEMA. The runtime
role has SELECT and INSERT on both new tables (audit.roles).
"""

from importlib import import_module

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION distribution_shipment_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    request_lab bigint;
    request_status text;
    contact_lab bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a shipment never changes (shipment %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT lab_id, status FROM %I.distribution_distributionrequest WHERE id = $1',
        TG_TABLE_SCHEMA) INTO request_lab, request_status USING NEW.request_id;
    EXECUTE format('SELECT lab_id FROM %I.deposits_contact WHERE id = $1', TG_TABLE_SCHEMA)
        INTO contact_lab USING NEW.responsible_id;
    IF request_lab IS DISTINCT FROM NEW.lab_id OR contact_lab IS DISTINCT FROM NEW.lab_id
       OR request_status IS DISTINCT FROM 'approved' THEN
        RAISE EXCEPTION 'a shipment is of an approved request of its lab (shipment %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_shipmentvial_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    same_request boolean;
    reserved boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'the vials of a shipment never change'
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT s.request_id = l.request_id FROM %1$I.distribution_shipment s,'
        ' %1$I.distribution_requestline l WHERE s.id = $1 AND l.id = $2', TG_TABLE_SCHEMA)
        INTO same_request USING NEW.shipment_id, NEW.line_id;
    EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_vialreservation'
        ' WHERE line_id = $1 AND vial_id = $2 AND ended_at IS NULL)', TG_TABLE_SCHEMA)
        INTO reserved USING NEW.line_id, NEW.vial_id;
    IF same_request IS NOT TRUE OR NOT reserved THEN
        RAISE EXCEPTION 'a shipment sends a vial its request reserved (vial %)', NEW.vial_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- At commit: the request is shipped and the shipment holds exactly what it reserved.
CREATE FUNCTION distribution_shipment_complete() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    request_status text;
    not_shipped bigint;
    differ bigint;
BEGIN
    EXECUTE format('SELECT status FROM %I.distribution_distributionrequest WHERE id = $1',
        TG_TABLE_SCHEMA) INTO request_status USING NEW.request_id;
    -- Every reservation of the request ended as shipped: none open, none ended otherwise.
    EXECUTE format('SELECT count(*) FROM %1$I.distribution_vialreservation r'
        ' JOIN %1$I.distribution_requestline l ON l.id = r.line_id'
        ' WHERE l.request_id = $1 AND r.end_reason IS DISTINCT FROM ''shipped''', TG_TABLE_SCHEMA)
        INTO not_shipped USING NEW.request_id;
    -- The request's reservations and the shipment's vials, compared both ways, and any vial
    -- of the shipment that is not distributed.
    EXECUTE format('WITH shipped AS (SELECT r.line_id, r.vial_id'
        '   FROM %1$I.distribution_vialreservation r'
        '   JOIN %1$I.distribution_requestline l ON l.id = r.line_id'
        '   WHERE l.request_id = $1),'
        ' sent AS (SELECT line_id, vial_id FROM %1$I.distribution_shipmentvial'
        '   WHERE shipment_id = $2)'
        ' SELECT (SELECT count(*) FROM (SELECT * FROM shipped EXCEPT SELECT * FROM sent) a)'
        '      + (SELECT count(*) FROM (SELECT * FROM sent EXCEPT SELECT * FROM shipped) b)'
        '      + (SELECT count(*) FROM sent JOIN %1$I.lineage_vial v ON v.id = sent.vial_id'
        '         WHERE v.status <> ''distributed'')', TG_TABLE_SCHEMA)
        INTO differ USING NEW.request_id, NEW.id;
    IF request_status IS DISTINCT FROM 'shipped' OR not_shipped > 0 OR differ > 0 THEN
        RAISE EXCEPTION 'a shipment sends every vial its request reserved, and the request is shipped (shipment %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

-- From 0003, with approved > shipped once a shipment exists.
CREATE OR REPLACE FUNCTION distribution_request_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    has_shipment boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'requests are never deleted, refused ones neither (request %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'decided_by_id' - 'decided_at' - 'decision_reason'
            - 'cancelled_by_id' - 'cancelled_at' - 'cancel_reason' - 'updated_at')
       IS DISTINCT FROM
       (to_jsonb(OLD) - 'status' - 'decided_by_id' - 'decided_at' - 'decision_reason'
            - 'cancelled_by_id' - 'cancelled_at' - 'cancel_reason' - 'updated_at') THEN
        RAISE EXCEPTION 'what a request asks for never changes (request %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
        IF (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
            RAISE EXCEPTION 'a decision is written with its status, once (request %)', OLD.public_id
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT (
        OLD.status = 'submitted' AND NEW.status IN ('approved', 'rejected', 'cancelled')
        OR OLD.status = 'approved' AND NEW.status IN ('cancelled', 'shipped')
    ) THEN
        RAISE EXCEPTION 'a request cannot go from % to % (request %)', OLD.status, NEW.status,
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'approved' AND (NEW.decided_by_id IS DISTINCT FROM OLD.decided_by_id
       OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
       OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason) THEN
        RAISE EXCEPTION 'an approval stays as it was given (request %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status = 'shipped' THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_shipment WHERE request_id = $1)',
            TG_TABLE_SCHEMA) INTO has_shipment USING NEW.id;
        IF NOT has_shipment THEN
            RAISE EXCEPTION 'a request is shipped with its shipment (request %)', OLD.public_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- From 0003, with: ended as shipped only for a vial a shipment of its line holds.
CREATE OR REPLACE FUNCTION distribution_vialreservation_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    vial_lab bigint;
    vial_strain bigint;
    line_strain bigint;
    sent boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'reservations are never deleted: end them (reservation %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.ended_at IS NOT NULL
           OR (to_jsonb(NEW) - 'ended_at' - 'ended_by_id' - 'end_reason' - 'updated_at')
              IS DISTINCT FROM (to_jsonb(OLD) - 'ended_at' - 'ended_by_id' - 'end_reason' - 'updated_at') THEN
            RAISE EXCEPTION 'a reservation changes once, when it ends (reservation %)', OLD.public_id
                USING ERRCODE = 'restrict_violation';
        END IF;
        IF NEW.end_reason = 'shipped' THEN
            EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_shipmentvial'
                ' WHERE line_id = $1 AND vial_id = $2)', TG_TABLE_SCHEMA)
                INTO sent USING NEW.line_id, NEW.vial_id;
            IF NOT sent THEN
                RAISE EXCEPTION 'a reservation ends as shipped with its vial in a shipment (reservation %)',
                    OLD.public_id USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT v.lab_id, b.strain_id FROM %1$I.lineage_vial v'
        ' JOIN %1$I.lineage_batch b ON b.id = v.batch_id WHERE v.id = $1', TG_TABLE_SCHEMA)
        INTO vial_lab, vial_strain USING NEW.vial_id;
    EXECUTE format('SELECT strain_id FROM %I.distribution_requestline WHERE id = $1',
        TG_TABLE_SCHEMA) INTO line_strain USING NEW.line_id;
    IF NEW.ended_at IS NOT NULL OR vial_lab IS DISTINCT FROM NEW.lab_id
       OR vial_strain IS DISTINCT FROM line_strain THEN
        RAISE EXCEPTION 'a reservation opens for a vial of its line''s strain, in its lab (reservation %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- From 0003, with: a vial is distributed only when a shipment holds it.
CREATE OR REPLACE FUNCTION distribution_vial_reserved_by_request() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    held boolean;
    sent boolean;
    current_status text;
BEGIN
    -- The row as committed now, not as this queued event saw it.
    EXECUTE format('SELECT status FROM %I.lineage_vial WHERE id = $1', TG_TABLE_SCHEMA)
        INTO current_status USING NEW.id;
    EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_vialreservation'
        ' WHERE vial_id = $1 AND ended_at IS NULL)', TG_TABLE_SCHEMA) INTO held USING NEW.id;
    IF (current_status = 'reserved') IS DISTINCT FROM held THEN
        RAISE EXCEPTION 'a vial is reserved if and only if a request holds it (vial %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF current_status = 'distributed' THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_shipmentvial WHERE vial_id = $1)',
            TG_TABLE_SCHEMA) INTO sent USING NEW.id;
        IF NOT sent THEN
            RAISE EXCEPTION 'a vial is distributed only in a shipment (vial %)', NEW.public_id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION distribution_shipment_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_shipmentvial_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_shipment_complete() FROM PUBLIC;

CREATE TRIGGER distribution_shipment_guard BEFORE INSERT OR UPDATE OR DELETE ON distribution_shipment
    FOR EACH ROW EXECUTE FUNCTION distribution_shipment_guard();
CREATE TRIGGER distribution_shipmentvial_guard BEFORE INSERT OR UPDATE OR DELETE ON distribution_shipmentvial
    FOR EACH ROW EXECUTE FUNCTION distribution_shipmentvial_guard();
CREATE CONSTRAINT TRIGGER distribution_shipment_complete
    AFTER INSERT ON distribution_shipment DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION distribution_shipment_complete();
"""

# The 0003 bodies of the three replaced functions, read from that migration.
REVERSE = """
DROP TRIGGER distribution_shipment_complete ON distribution_shipment;
DROP TRIGGER distribution_shipmentvial_guard ON distribution_shipmentvial;
DROP TRIGGER distribution_shipment_guard ON distribution_shipment;
DROP FUNCTION distribution_shipment_complete();
DROP FUNCTION distribution_shipmentvial_guard();
DROP FUNCTION distribution_shipment_guard();
"""


def _from_0003(name: str) -> str:
    """The CREATE FUNCTION statement of `name` as migration 0003 wrote it, made a replace."""
    source: str = import_module("cultures.distribution.migrations.0003_guards").FUNCTIONS
    start = source.index(f"CREATE FUNCTION {name}()")
    end = source.index("$$;", start) + len("$$;")
    return "CREATE OR REPLACE" + source[start + len("CREATE") : end]


RESTORE = "\n".join(
    _from_0003(name)
    for name in (
        "distribution_request_guard",
        "distribution_vialreservation_guard",
        "distribution_vial_reserved_by_request",
    )
)


class Migration(migrations.Migration):
    dependencies = [("distribution", "0004_shipment")]

    operations = [
        attach_row_audit("distribution_shipment", label="distribution.shipment"),
        attach_row_audit("distribution_shipmentvial", label="distribution.shipmentvial"),
        migrations.RunSQL(FUNCTIONS, REVERSE + RESTORE),
    ]
