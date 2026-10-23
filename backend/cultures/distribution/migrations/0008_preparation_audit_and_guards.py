"""Row audit and triggers of the two-person shipment (#89), against every writer: QuerySet.update(),
raw SQL, psql (ADR 0009, amendment of 2026-10-22).

- distribution_shipmentpreparation: never deleted; inserted for an approved request of its lab,
  with a responsible contact of the lab, not withdrawn; the one update is the withdrawal, once,
  and never of a preparation a shipment confirmed.
- The shipment guard (from 0005) adds: a shipment without a preparation is of an approved
  request with no line of a regulated strain (an active restriction); a shipment with one is of
  a request awaiting confirmation, confirms its open preparation, repeats every fact of it
  (classified by and at are who prepared it and when), and is shipped by neither the preparer
  nor the approver.
- The request guard (from 0005) adds approved > awaiting_confirmation only with an open
  preparation, awaiting_confirmation > approved only once it is withdrawn, and
  awaiting_confirmation > shipped (with its shipment). The approval stays as it was given in
  both states.

The deferred completeness check of 0005 is unchanged: it holds for a confirmed shipment as for
any. The functions pin their search_path and reach other tables through TG_TABLE_SCHEMA. The
runtime role has SELECT, INSERT and UPDATE on the preparations (audit.roles).
"""

from importlib import import_module

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION distribution_shipmentpreparation_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    request_lab bigint;
    request_status text;
    contact_lab bigint;
    confirmed boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a prepared shipment is never deleted: withdraw it (preparation %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.withdrawn_at IS NOT NULL
           OR (to_jsonb(NEW) - 'withdrawn_at' - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at')
              IS DISTINCT FROM (to_jsonb(OLD) - 'withdrawn_at' - 'withdrawn_by_id' - 'withdraw_reason' - 'updated_at') THEN
            RAISE EXCEPTION 'a prepared shipment changes once, when it is withdrawn (preparation %)', OLD.public_id
                USING ERRCODE = 'restrict_violation';
        END IF;
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_shipment WHERE preparation_id = $1)',
            TG_TABLE_SCHEMA) INTO confirmed USING OLD.id;
        IF confirmed THEN
            RAISE EXCEPTION 'a confirmed preparation is not withdrawn (preparation %)', OLD.public_id
                USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT lab_id, status FROM %I.distribution_distributionrequest WHERE id = $1',
        TG_TABLE_SCHEMA) INTO request_lab, request_status USING NEW.request_id;
    EXECUTE format('SELECT lab_id FROM %I.deposits_contact WHERE id = $1', TG_TABLE_SCHEMA)
        INTO contact_lab USING NEW.responsible_id;
    IF request_lab IS DISTINCT FROM NEW.lab_id OR contact_lab IS DISTINCT FROM NEW.lab_id
       OR request_status IS DISTINCT FROM 'approved' OR NEW.withdrawn_at IS NOT NULL THEN
        RAISE EXCEPTION 'a shipment is prepared for an approved request of its lab (preparation %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- From 0005, with the two steps of a regulated request.
CREATE OR REPLACE FUNCTION distribution_shipment_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    request_lab bigint;
    request_status text;
    approver bigint;
    contact_lab bigint;
    regulated boolean;
    prep record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a shipment never changes (shipment %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT lab_id, status, decided_by_id FROM %I.distribution_distributionrequest'
        ' WHERE id = $1', TG_TABLE_SCHEMA) INTO request_lab, request_status, approver
        USING NEW.request_id;
    EXECUTE format('SELECT lab_id FROM %I.deposits_contact WHERE id = $1', TG_TABLE_SCHEMA)
        INTO contact_lab USING NEW.responsible_id;
    IF request_lab IS DISTINCT FROM NEW.lab_id OR contact_lab IS DISTINCT FROM NEW.lab_id
       OR request_status IS DISTINCT FROM
          (CASE WHEN NEW.preparation_id IS NULL THEN 'approved' ELSE 'awaiting_confirmation' END) THEN
        RAISE EXCEPTION 'a shipment is of an approved request of its lab (shipment %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.preparation_id IS NULL THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.distribution_requestline l'
            ' JOIN %1$I.strains_strainrestriction r ON r.strain_id = l.strain_id'
            ' WHERE l.request_id = $1 AND r.ended_at IS NULL)', TG_TABLE_SCHEMA)
            INTO regulated USING NEW.request_id;
        IF regulated THEN
            RAISE EXCEPTION 'a regulated strain leaves only with a confirmed preparation (shipment %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    EXECUTE format('SELECT * FROM %I.distribution_shipmentpreparation WHERE id = $1',
        TG_TABLE_SCHEMA) INTO prep USING NEW.preparation_id;
    IF prep.request_id IS DISTINCT FROM NEW.request_id OR prep.withdrawn_at IS NOT NULL THEN
        RAISE EXCEPTION 'a shipment confirms the open preparation of its request (shipment %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF (prep.transport_class, prep.classification_basis, prep.basis_note, prep.packing_instruction,
        prep.coolant, prep.coolant_kg, prep.responsible_id, prep.carrier, prep.tracking_number,
        prep.prepared_by_id, prep.prepared_at)
       IS DISTINCT FROM
       (NEW.transport_class, NEW.classification_basis, NEW.basis_note, NEW.packing_instruction,
        NEW.coolant, NEW.coolant_kg, NEW.responsible_id, NEW.carrier, NEW.tracking_number,
        NEW.classified_by_id, NEW.classified_at) THEN
        RAISE EXCEPTION 'a confirmed shipment is what was prepared (shipment %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.shipped_by_id = prep.prepared_by_id THEN
        RAISE EXCEPTION 'nobody confirms their own preparation (shipment %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.shipped_by_id IS NOT DISTINCT FROM approver THEN
        RAISE EXCEPTION 'nobody confirms the shipment of their own approval (shipment %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- From 0005, with approved > awaiting_confirmation > approved or shipped.
CREATE OR REPLACE FUNCTION distribution_request_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    has_shipment boolean;
    prepared boolean;
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
        OR OLD.status = 'approved' AND NEW.status IN ('cancelled', 'shipped', 'awaiting_confirmation')
        OR OLD.status = 'awaiting_confirmation' AND NEW.status IN ('approved', 'shipped')
    ) THEN
        RAISE EXCEPTION 'a request cannot go from % to % (request %)', OLD.status, NEW.status,
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status IN ('approved', 'awaiting_confirmation')
       AND (NEW.decided_by_id IS DISTINCT FROM OLD.decided_by_id
            OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
            OR NEW.decision_reason IS DISTINCT FROM OLD.decision_reason) THEN
        RAISE EXCEPTION 'an approval stays as it was given (request %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status = 'awaiting_confirmation' OR OLD.status = 'awaiting_confirmation' AND NEW.status = 'approved' THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_shipmentpreparation'
            ' WHERE request_id = $1 AND withdrawn_at IS NULL)', TG_TABLE_SCHEMA)
            INTO prepared USING NEW.id;
        IF prepared IS DISTINCT FROM (NEW.status = 'awaiting_confirmation') THEN
            RAISE EXCEPTION 'a request awaits confirmation while, and only while, its shipment is prepared (request %)',
                OLD.public_id USING ERRCODE = 'check_violation';
        END IF;
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

REVOKE ALL ON FUNCTION distribution_shipmentpreparation_guard() FROM PUBLIC;

CREATE TRIGGER distribution_shipmentpreparation_guard
    BEFORE INSERT OR UPDATE OR DELETE ON distribution_shipmentpreparation
    FOR EACH ROW EXECUTE FUNCTION distribution_shipmentpreparation_guard();
"""

REVERSE = """
DROP TRIGGER distribution_shipmentpreparation_guard ON distribution_shipmentpreparation;
DROP FUNCTION distribution_shipmentpreparation_guard();
"""


def _from_0005(name: str) -> str:
    """The function `name` as migration 0005 wrote it, as a replace."""
    source: str = import_module(
        "cultures.distribution.migrations.0005_shipment_audit_and_guards"
    ).FUNCTIONS
    start = source.index(f"FUNCTION {name}()")
    start = source.rindex("CREATE", 0, start)
    end = source.index("$$;", source.index("$$", start) + 2) + len("$$;")
    body = source[start:end]
    return body if body.startswith("CREATE OR REPLACE") else "CREATE OR REPLACE" + body[6:]


RESTORE = "\n".join(
    _from_0005(name) for name in ("distribution_shipment_guard", "distribution_request_guard")
)


class Migration(migrations.Migration):
    dependencies = [("distribution", "0007_shipment_preparation")]

    operations = [
        attach_row_audit(
            "distribution_shipmentpreparation", label="distribution.shipmentpreparation"
        ),
        migrations.RunSQL(FUNCTIONS, REVERSE + RESTORE),
    ]
