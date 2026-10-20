"""Triggers that hold what the distribution services promise, against every writer:
QuerySet.update(), raw SQL, psql (ADR 0008, amendment of 2026-10-20, #18).

- distribution_requester: never deleted; its public id, lab and contact never change.
- distribution_document: frozen; on insert sha256 and size_bytes are those of the content.
- distribution_recipientpermit: never deleted; it changes once, when it is ended.
- distribution_requestcounter: never deleted; its lab and year never change, its number only
  rises.
- distribution_distributionrequest: never deleted; what was asked never changes; the status
  moves only along distribution.models.REQUEST_EDGES (tests compare all 16 pairs), and a
  decision is written once, with its status.
- distribution_requestline: frozen; on insert it belongs to a submitted request of its lab,
  its strain is of that lab, and its terms are a version of the strain's deposit with that
  version's MTA (the pinned versions).
- distribution_linepermit: frozen; the permit is the line's requester's.
- distribution_mtaacceptance: frozen; on insert the request waits for a decision and one of its
  lines is pinned to the MTA version.
- distribution_vialreservation: never deleted; it is opened for a vial of its line's strain in
  its lab, and changes once, when it ends.
- At commit (deferred constraint triggers): a vial is reserved if and only if it has an open
  reservation, so neither side can be changed without the other.

updated_at may change with any allowed write. The functions pin their search_path and reach
other tables through TG_TABLE_SCHEMA. Row triggers do not fire on TRUNCATE, so Django's test
flush still works; the runtime role has no TRUNCATE and no DELETE here (audit.roles).
"""

from django.db import migrations

FUNCTIONS = r"""
CREATE FUNCTION distribution_requester_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'requesters are never deleted (requester %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.lab_id IS DISTINCT FROM OLD.lab_id OR NEW.contact_id IS DISTINCT FROM OLD.contact_id THEN
        RAISE EXCEPTION 'a requester keeps its public id, lab and contact (requester %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_document_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.sha256 IS DISTINCT FROM encode(sha256(NEW.content), 'hex')
           OR NEW.size_bytes IS DISTINCT FROM octet_length(NEW.content) THEN
            RAISE EXCEPTION 'sha256 and size are those of the content (document %)', NEW.public_id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'a document is frozen (document %)', OLD.public_id
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE FUNCTION distribution_recipientpermit_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'permits are never deleted: end them (permit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.ended_on IS NOT NULL
       OR (to_jsonb(NEW) - 'ended_on' - 'end_reason' - 'updated_at')
          IS DISTINCT FROM (to_jsonb(OLD) - 'ended_on' - 'end_reason' - 'updated_at') THEN
        RAISE EXCEPTION 'a permit changes once, when it is ended (permit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_requestcounter_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' OR NEW.lab_id IS DISTINCT FROM OLD.lab_id OR NEW.year IS DISTINCT FROM OLD.year
       OR NEW.last_number < OLD.last_number THEN
        RAISE EXCEPTION 'a request counter only rises: a number is never given twice'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_request_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
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
        OR OLD.status = 'approved' AND NEW.status = 'cancelled'
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
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_requestline_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    request_lab bigint;
    request_status text;
    strain_lab bigint;
    terms_strain bigint;
    terms_mta bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a request line never changes (line %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT lab_id, status FROM %I.distribution_distributionrequest WHERE id = $1',
        TG_TABLE_SCHEMA) INTO request_lab, request_status USING NEW.request_id;
    EXECUTE format('SELECT lab_id FROM %I.strains_strain WHERE id = $1', TG_TABLE_SCHEMA)
        INTO strain_lab USING NEW.strain_id;
    EXECUTE format('SELECT d.strain_id, t.mta_id FROM %1$I.deposits_depositterms t'
        ' JOIN %1$I.deposits_deposit d ON d.id = t.deposit_id WHERE t.id = $1', TG_TABLE_SCHEMA)
        INTO terms_strain, terms_mta USING NEW.terms_id;
    IF request_lab IS DISTINCT FROM NEW.lab_id OR strain_lab IS DISTINCT FROM NEW.lab_id THEN
        RAISE EXCEPTION 'a line, its request and its strain are of one lab (line %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF request_status IS DISTINCT FROM 'submitted' THEN
        RAISE EXCEPTION 'lines are added when a request is entered (line %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF terms_strain IS DISTINCT FROM NEW.strain_id OR terms_mta IS DISTINCT FROM NEW.mta_id THEN
        RAISE EXCEPTION 'a line pins a terms version of its strain and that version''s MTA (line %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_linepermit_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    line_requester bigint;
    permit_requester bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'the permits a line was approved against never change'
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT r.requester_id FROM %1$I.distribution_requestline l'
        ' JOIN %1$I.distribution_distributionrequest r ON r.id = l.request_id WHERE l.id = $1',
        TG_TABLE_SCHEMA) INTO line_requester USING NEW.line_id;
    EXECUTE format('SELECT requester_id FROM %I.distribution_recipientpermit WHERE id = $1',
        TG_TABLE_SCHEMA) INTO permit_requester USING NEW.permit_id;
    IF line_requester IS DISTINCT FROM permit_requester THEN
        RAISE EXCEPTION 'a line is approved against its requester''s permits'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_mtaacceptance_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    request_lab bigint;
    request_status text;
    pinned boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'an MTA acceptance never changes (acceptance %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT lab_id, status FROM %I.distribution_distributionrequest WHERE id = $1',
        TG_TABLE_SCHEMA) INTO request_lab, request_status USING NEW.request_id;
    EXECUTE format('SELECT EXISTS (SELECT FROM %I.distribution_requestline'
        ' WHERE request_id = $1 AND mta_id = $2)', TG_TABLE_SCHEMA)
        INTO pinned USING NEW.request_id, NEW.mta_id;
    IF request_lab IS DISTINCT FROM NEW.lab_id OR request_status IS DISTINCT FROM 'submitted'
       OR NOT pinned THEN
        RAISE EXCEPTION 'an acceptance is of an MTA version a line of a waiting request is pinned to (acceptance %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION distribution_vialreservation_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    vial_lab bigint;
    vial_strain bigint;
    line_strain bigint;
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

-- At commit: an open reservation's vial is reserved.
CREATE FUNCTION distribution_reservation_holds_vial() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    still_open boolean;
    vial_status text;
BEGIN
    -- The rows as committed now, not as this queued event saw them.
    EXECUTE format('SELECT r.ended_at IS NULL, v.status FROM %1$I.distribution_vialreservation r'
        ' JOIN %1$I.lineage_vial v ON v.id = r.vial_id WHERE r.id = $1', TG_TABLE_SCHEMA)
        INTO still_open, vial_status USING NEW.id;
    IF still_open AND vial_status IS DISTINCT FROM 'reserved' THEN
        RAISE EXCEPTION 'an open reservation holds a reserved vial (reservation %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

-- At commit: a vial is reserved if and only if it has an open reservation.
CREATE FUNCTION distribution_vial_reserved_by_request() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    held boolean;
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
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION distribution_requester_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_document_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_recipientpermit_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_requestcounter_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_request_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_requestline_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_linepermit_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_mtaacceptance_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_vialreservation_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_reservation_holds_vial() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_vial_reserved_by_request() FROM PUBLIC;

CREATE TRIGGER distribution_requester_guard BEFORE UPDATE OR DELETE ON distribution_requester
    FOR EACH ROW EXECUTE FUNCTION distribution_requester_guard();
CREATE TRIGGER distribution_document_guard BEFORE INSERT OR UPDATE OR DELETE ON distribution_document
    FOR EACH ROW EXECUTE FUNCTION distribution_document_guard();
CREATE TRIGGER distribution_recipientpermit_guard BEFORE UPDATE OR DELETE ON distribution_recipientpermit
    FOR EACH ROW EXECUTE FUNCTION distribution_recipientpermit_guard();
CREATE TRIGGER distribution_requestcounter_guard BEFORE UPDATE OR DELETE ON distribution_requestcounter
    FOR EACH ROW EXECUTE FUNCTION distribution_requestcounter_guard();
CREATE TRIGGER distribution_request_guard BEFORE UPDATE OR DELETE ON distribution_distributionrequest
    FOR EACH ROW EXECUTE FUNCTION distribution_request_guard();
CREATE TRIGGER distribution_requestline_guard BEFORE INSERT OR UPDATE OR DELETE ON distribution_requestline
    FOR EACH ROW EXECUTE FUNCTION distribution_requestline_guard();
CREATE TRIGGER distribution_linepermit_guard BEFORE INSERT OR UPDATE OR DELETE ON distribution_linepermit
    FOR EACH ROW EXECUTE FUNCTION distribution_linepermit_guard();
CREATE TRIGGER distribution_mtaacceptance_guard BEFORE INSERT OR UPDATE OR DELETE ON distribution_mtaacceptance
    FOR EACH ROW EXECUTE FUNCTION distribution_mtaacceptance_guard();
CREATE TRIGGER distribution_vialreservation_guard BEFORE INSERT OR UPDATE OR DELETE ON distribution_vialreservation
    FOR EACH ROW EXECUTE FUNCTION distribution_vialreservation_guard();
CREATE CONSTRAINT TRIGGER distribution_reservation_holds_vial
    AFTER INSERT OR UPDATE ON distribution_vialreservation DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION distribution_reservation_holds_vial();
CREATE CONSTRAINT TRIGGER distribution_vial_reserved_by_request
    AFTER INSERT OR UPDATE OF status ON lineage_vial DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION distribution_vial_reserved_by_request();
"""

REVERSE = """
DROP TRIGGER distribution_vial_reserved_by_request ON lineage_vial;
DROP TRIGGER distribution_reservation_holds_vial ON distribution_vialreservation;
DROP TRIGGER distribution_vialreservation_guard ON distribution_vialreservation;
DROP TRIGGER distribution_mtaacceptance_guard ON distribution_mtaacceptance;
DROP TRIGGER distribution_linepermit_guard ON distribution_linepermit;
DROP TRIGGER distribution_requestline_guard ON distribution_requestline;
DROP TRIGGER distribution_request_guard ON distribution_distributionrequest;
DROP TRIGGER distribution_requestcounter_guard ON distribution_requestcounter;
DROP TRIGGER distribution_recipientpermit_guard ON distribution_recipientpermit;
DROP TRIGGER distribution_document_guard ON distribution_document;
DROP TRIGGER distribution_requester_guard ON distribution_requester;
DROP FUNCTION distribution_vial_reserved_by_request();
DROP FUNCTION distribution_reservation_holds_vial();
DROP FUNCTION distribution_vialreservation_guard();
DROP FUNCTION distribution_mtaacceptance_guard();
DROP FUNCTION distribution_linepermit_guard();
DROP FUNCTION distribution_requestline_guard();
DROP FUNCTION distribution_request_guard();
DROP FUNCTION distribution_requestcounter_guard();
DROP FUNCTION distribution_recipientpermit_guard();
DROP FUNCTION distribution_document_guard();
DROP FUNCTION distribution_requester_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("distribution", "0002_row_audit")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
