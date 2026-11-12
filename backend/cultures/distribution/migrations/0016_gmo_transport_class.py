"""The number a GMO shipment travels under follows the strains' own records (#197).

Two helpers and the two guards that call them:

- distribution_recorded_transport_class: the class the records of a request's strains force, or
  NULL where they force none. `distribution.policy.recorded_transport_class` asks the same in
  Python, and a parity test compares the two.
- distribution_check_gmo_class: the rule of one package. A request with a GMO line is never
  exempt (#173), and where the records force a number the package carries that number.
- The preparation guard and the shipment guard (from 0008) call it on every INSERT, so no
  QuerySet.update(), raw SQL or psql session writes a package the service would refuse. The
  shipment guard asks it of both its paths, with and without a preparation.

An unknown pathogenicity forces nothing: it is what most deposits record, and the shipper
states the class with its basis. Rows written before this migration are untouched.

The two helpers are not revoked from PUBLIC, unlike the trigger functions: a guard calls them as
the role that writes the row. They pin their search_path and reach the other tables through the
schema their caller passes.
"""

from importlib import import_module

from django.db import migrations

FUNCTIONS = r"""
-- #197: the class a request's own records force, or NULL where the shipper states it. The one
-- reading of the pathogenicity for transport, which policy.recorded_transport_class repeats in
-- Python. Group 2 is the first group recorded as pathogenic to humans (Directive 2000/54/EC,
-- Art. 2, government order 361/2007 Sb., § 36(2) a)); animals are the strain's own column.
-- Plants are not read here: the transport question asks about humans and animals.
CREATE FUNCTION distribution_recorded_transport_class(schema_name text, request bigint)
    RETURNS text LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    pathogenic boolean;
    unknown boolean;
BEGIN
    EXECUTE format('SELECT'
        ' bool_or(s.risk_group >= 2 OR s.animal_pathogenicity = ''pathogenic''),'
        ' bool_or(s.risk_group < 2 AND s.animal_pathogenicity = ''unknown'')'
        ' FROM %1$I.distribution_requestline l'
        ' JOIN %1$I.strains_strain s ON s.id = l.strain_id'
        ' WHERE l.request_id = $1', schema_name)
        INTO pathogenic, unknown USING request;
    IF pathogenic THEN
        RETURN 'un3373';
    END IF;
    -- NULL for a request with no line too: nothing recorded forces nothing.
    IF unknown IS DISTINCT FROM false THEN
        RETURN NULL;
    END IF;
    RETURN 'un3245';
END;
$$;

-- The rule of one package, for the preparation guard and the shipment guard alike.
CREATE FUNCTION distribution_check_gmo_class(schema_name text, request bigint,
    transport_class text, package uuid) RETURNS void
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    gmo boolean;
    forced text;
BEGIN
    EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.distribution_requestline l'
        ' JOIN %1$I.strains_strainrestriction r ON r.strain_id = l.strain_id'
        ' WHERE l.request_id = $1 AND r.ended_at IS NULL AND r.kind = ''gmo'')', schema_name)
        INTO gmo USING request;
    IF NOT gmo THEN
        RETURN;
    END IF;
    IF transport_class = 'not_subject' THEN
        RAISE EXCEPTION 'a genetically modified organism is not exempt from the transport rules (package %)',
            package USING ERRCODE = 'check_violation';
    END IF;
    EXECUTE format('SELECT %1$I.distribution_recorded_transport_class($1, $2)', schema_name)
        INTO forced USING schema_name, request;
    IF forced IS NOT NULL AND transport_class IS DISTINCT FROM forced THEN
        RAISE EXCEPTION 'a genetically modified organism travels under the number the records of its request force, % (package %)',
            forced, package USING ERRCODE = 'check_violation';
    END IF;
END;
$$;

-- From 0008, with the class a GMO line's records force (#197).
CREATE OR REPLACE FUNCTION distribution_shipmentpreparation_guard() RETURNS trigger
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
    EXECUTE format('SELECT %1$I.distribution_check_gmo_class($1, $2, $3, $4)', TG_TABLE_SCHEMA)
        USING TG_TABLE_SCHEMA, NEW.request_id, NEW.transport_class, NEW.public_id;
    RETURN NEW;
END;
$$;

-- From 0008, with the same check on both paths of a shipment (#197).
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
    EXECUTE format('SELECT %1$I.distribution_check_gmo_class($1, $2, $3, $4)', TG_TABLE_SCHEMA)
        USING TG_TABLE_SCHEMA, NEW.request_id, NEW.transport_class, NEW.public_id;
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
"""

REVERSE = """
DROP FUNCTION distribution_check_gmo_class(text, bigint, text, uuid);
DROP FUNCTION distribution_recorded_transport_class(text, bigint);
"""


def _from_0008(name: str) -> str:
    """The function `name` as migration 0008 wrote it, as a replace: the reverse of this one."""
    source: str = import_module(
        "cultures.distribution.migrations.0008_preparation_audit_and_guards"
    ).FUNCTIONS
    start = source.index(f"FUNCTION {name}()")
    start = source.rindex("CREATE", 0, start)
    end = source.index("$$;", source.index("$$", start) + 2) + len("$$;")
    body = source[start:end]
    return body if body.startswith("CREATE OR REPLACE") else "CREATE OR REPLACE" + body[6:]


RESTORE = "\n".join(
    _from_0008(name)
    for name in ("distribution_shipmentpreparation_guard", "distribution_shipment_guard")
)


class Migration(migrations.Migration):
    dependencies = [("distribution", "0015_un3245_for_a_gmo")]

    operations = [migrations.RunSQL(FUNCTIONS, RESTORE + REVERSE)]
