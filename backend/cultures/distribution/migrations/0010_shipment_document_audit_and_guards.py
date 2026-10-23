"""Row audit and triggers of a shipment's documents (#90), against every writer: QuerySet.update(),
raw SQL, psql (ADR 0009, amendment of 2026-10-23).

- distribution_shipmentdocument: never changed or deleted. On insert: text_sha256 is the SHA-256
  of the text as stored (UTF-8); the shipment is of the document's lab and was written by this
  same transaction (its row's xmin is still in progress, which only this transaction's own rows
  are when visible), so a document is never added to a shipment later; a line is of the
  shipment's request; an ABS sheet only for a line whose pinned terms are in scope of 511/2014,
  a register entry only for a line of a strain with an active cz_vrat or cz_rat restriction.
- At commit (deferred constraint trigger on the shipment): the shipment has its delivery note,
  an ABS sheet for every line whose terms are in scope, and a register entry for every line of
  a strain with an active cz_vrat or cz_rat restriction.

The text is personal (it names the responsible person): the row audit stores the marker, the
SHA-256 is audited. The runtime role has SELECT and INSERT (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION distribution_shipmentdocument_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    shipment_lab bigint;
    shipment_xmin bigint;
    request bigint;
    line_request bigint;
    in_scope boolean;
    registered boolean;
    current_xid bigint := pg_current_xact_id()::text::bigint;
    candidate bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a shipment document is kept as sent (document %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.text_sha256 IS DISTINCT FROM encode(sha256(convert_to(NEW.text, 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'text_sha256 is not the SHA-256 of the text (document %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    EXECUTE format('SELECT lab_id, request_id, xmin::text::bigint FROM %I.distribution_shipment'
        ' WHERE id = $1', TG_TABLE_SCHEMA) INTO shipment_lab, request, shipment_xmin
        USING NEW.shipment_id;
    -- xmin is a 32-bit xid: give it the epoch of the current one. A subtransaction's xid is a
    -- little ahead of it; one far ahead is of the epoch before (the counter wrapped between).
    candidate := (current_xid >> 32 << 32) + shipment_xmin;
    IF candidate > current_xid + (1::bigint << 31) THEN
        candidate := candidate - (1::bigint << 32);
    END IF;
    IF shipment_lab IS DISTINCT FROM NEW.lab_id
       OR candidate < 0 OR pg_xact_status(candidate::text::xid8) IS DISTINCT FROM 'in progress' THEN
        RAISE EXCEPTION 'a shipment document is written with its shipment, in its lab (document %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.line_id IS NOT NULL THEN
        EXECUTE format('SELECT l.request_id, t.abs_scope = ''in_scope'', EXISTS (SELECT FROM'
            ' %1$I.strains_strainrestriction r WHERE r.strain_id = l.strain_id'
            ' AND r.ended_at IS NULL AND r.kind IN (''cz_vrat'', ''cz_rat''))'
            ' FROM %1$I.distribution_requestline l JOIN %1$I.deposits_depositterms t'
            ' ON t.id = l.terms_id WHERE l.id = $1', TG_TABLE_SCHEMA)
            INTO line_request, in_scope, registered USING NEW.line_id;
        IF line_request IS DISTINCT FROM request THEN
            RAISE EXCEPTION 'a shipment document is about a line of its request (document %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.kind = 'abs_sheet' AND in_scope IS NOT TRUE
           OR NEW.kind = 'register_entry' AND registered IS NOT TRUE THEN
            RAISE EXCEPTION 'a % is written only for a line that needs one (document %)',
                NEW.kind, NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- At commit: every document the shipment needs exists.
CREATE FUNCTION distribution_shipment_documented() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    missing boolean;
BEGIN
    EXECUTE format('SELECT NOT EXISTS (SELECT FROM %1$I.distribution_shipmentdocument'
        ' WHERE shipment_id = $1 AND kind = ''delivery_note'')'
        ' OR EXISTS (SELECT FROM %1$I.distribution_requestline l'
        '   JOIN %1$I.deposits_depositterms t ON t.id = l.terms_id'
        '   WHERE l.request_id = $2 AND t.abs_scope = ''in_scope'' AND NOT EXISTS (SELECT FROM'
        '   %1$I.distribution_shipmentdocument d WHERE d.shipment_id = $1'
        '   AND d.kind = ''abs_sheet'' AND d.line_id = l.id))'
        ' OR EXISTS (SELECT FROM %1$I.distribution_requestline l'
        '   WHERE l.request_id = $2 AND EXISTS (SELECT FROM %1$I.strains_strainrestriction r'
        '   WHERE r.strain_id = l.strain_id AND r.ended_at IS NULL'
        '   AND r.kind IN (''cz_vrat'', ''cz_rat'')) AND NOT EXISTS (SELECT FROM'
        '   %1$I.distribution_shipmentdocument d WHERE d.shipment_id = $1'
        '   AND d.kind = ''register_entry'' AND d.line_id = l.id))', TG_TABLE_SCHEMA)
        INTO missing USING NEW.id, NEW.request_id;
    IF missing THEN
        RAISE EXCEPTION 'a shipment leaves with every document it needs (shipment %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION distribution_shipmentdocument_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION distribution_shipment_documented() FROM PUBLIC;

CREATE TRIGGER distribution_shipmentdocument_guard
    BEFORE INSERT OR UPDATE OR DELETE ON distribution_shipmentdocument
    FOR EACH ROW EXECUTE FUNCTION distribution_shipmentdocument_guard();
CREATE CONSTRAINT TRIGGER distribution_shipment_documented
    AFTER INSERT ON distribution_shipment DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION distribution_shipment_documented();
"""

REVERSE = """
DROP TRIGGER distribution_shipment_documented ON distribution_shipment;
DROP TRIGGER distribution_shipmentdocument_guard ON distribution_shipmentdocument;
DROP FUNCTION distribution_shipment_documented();
DROP FUNCTION distribution_shipmentdocument_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("distribution", "0009_shipment_document")]

    operations = [
        attach_row_audit(
            "distribution_shipmentdocument",
            label="distribution.shipmentdocument",
            personal=("text",),
        ),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
