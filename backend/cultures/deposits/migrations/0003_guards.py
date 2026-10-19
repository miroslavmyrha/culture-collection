"""Triggers that hold what the services promise, against every writer: QuerySet.update(),
raw SQL, psql (ADR 0008, amendment of 2026-10-19).

- deposits_contact: never deleted (erasure empties it in place); its public id and lab
  never change, and an erasure is never undone.
- deposits_depositor: never deleted; its public id, lab and contact never change.
- deposits_mtatemplate: never changed or deleted; on insert, text_sha256 must be the
  SHA-256 of the text as stored (UTF-8).
- deposits_deposit: never deleted; the receipt facts never change; the status moves only
  received > checking > accepted or rejected, and a decided deposit never changes.
- deposits_depositterms: never deleted; a version only stops being active.
- deposits_termsuse: never changed or deleted.
updated_at may change with any allowed write. Row triggers do not fire on TRUNCATE, so
Django's test flush still works; the runtime role has no TRUNCATE (audit.roles).
The functions are owned by the migration role and pin their search_path.
"""

from django.db import migrations

FUNCTIONS = r"""
CREATE FUNCTION deposits_contact_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'contacts are never deleted: erase them (contact %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.lab_id IS DISTINCT FROM OLD.lab_id THEN
        RAISE EXCEPTION 'a contact keeps its public id and lab (contact %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.erased_at IS NOT NULL AND NEW.erased_at IS DISTINCT FROM OLD.erased_at THEN
        RAISE EXCEPTION 'an erasure is never undone (contact %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION deposits_depositor_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'depositors are never deleted (depositor %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.public_id IS DISTINCT FROM OLD.public_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.lab_id IS DISTINCT FROM OLD.lab_id OR NEW.contact_id IS DISTINCT FROM OLD.contact_id THEN
        RAISE EXCEPTION 'a depositor keeps its public id, lab and contact (depositor %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION deposits_mtatemplate_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.text_sha256 IS DISTINCT FROM encode(sha256(convert_to(NEW.text, 'UTF8')), 'hex') THEN
            RAISE EXCEPTION 'text_sha256 is not the SHA-256 of the text (MTA % v%)', NEW.code, NEW.version
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'an MTA version is frozen: publish a new version (MTA % v%)', OLD.code, OLD.version
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE FUNCTION deposits_deposit_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'deposits are never deleted (deposit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status IN ('accepted', 'rejected')
       AND (to_jsonb(NEW) - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'a decided deposit never changes (deposit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'status' - 'strain_id' - 'decided_at' - 'rejection_reason' - 'updated_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'strain_id' - 'decided_at' - 'rejection_reason' - 'updated_at') THEN
        RAISE EXCEPTION 'the receipt of a deposit never changes (deposit %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
           OLD.status = 'received' AND NEW.status = 'checking'
           OR OLD.status = 'checking' AND NEW.status IN ('accepted', 'rejected')) THEN
        RAISE EXCEPTION 'a % deposit cannot become % (deposit %)', OLD.status, NEW.status, OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION deposits_depositterms_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'terms are history and never deleted'
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF (to_jsonb(NEW) - 'is_active' - 'updated_at') IS DISTINCT FROM (to_jsonb(OLD) - 'is_active' - 'updated_at')
       OR NEW.is_active AND NOT OLD.is_active THEN
        RAISE EXCEPTION 'a terms version only stops being active'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION deposits_termsuse_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'the uses of a terms version never change'
        USING ERRCODE = 'restrict_violation';
END;
$$;

REVOKE ALL ON FUNCTION deposits_contact_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION deposits_depositor_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION deposits_mtatemplate_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION deposits_deposit_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION deposits_depositterms_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION deposits_termsuse_guard() FROM PUBLIC;

CREATE TRIGGER deposits_contact_guard BEFORE UPDATE OR DELETE ON deposits_contact
    FOR EACH ROW EXECUTE FUNCTION deposits_contact_guard();
CREATE TRIGGER deposits_depositor_guard BEFORE UPDATE OR DELETE ON deposits_depositor
    FOR EACH ROW EXECUTE FUNCTION deposits_depositor_guard();
CREATE TRIGGER deposits_mtatemplate_guard BEFORE INSERT OR UPDATE OR DELETE ON deposits_mtatemplate
    FOR EACH ROW EXECUTE FUNCTION deposits_mtatemplate_guard();
CREATE TRIGGER deposits_deposit_guard BEFORE UPDATE OR DELETE ON deposits_deposit
    FOR EACH ROW EXECUTE FUNCTION deposits_deposit_guard();
CREATE TRIGGER deposits_depositterms_guard BEFORE UPDATE OR DELETE ON deposits_depositterms
    FOR EACH ROW EXECUTE FUNCTION deposits_depositterms_guard();
CREATE TRIGGER deposits_termsuse_guard BEFORE UPDATE OR DELETE ON deposits_termsuse
    FOR EACH ROW EXECUTE FUNCTION deposits_termsuse_guard();
"""

REVERSE = """
DROP TRIGGER deposits_termsuse_guard ON deposits_termsuse;
DROP TRIGGER deposits_depositterms_guard ON deposits_depositterms;
DROP TRIGGER deposits_deposit_guard ON deposits_deposit;
DROP TRIGGER deposits_mtatemplate_guard ON deposits_mtatemplate;
DROP TRIGGER deposits_depositor_guard ON deposits_depositor;
DROP TRIGGER deposits_contact_guard ON deposits_contact;
DROP FUNCTION deposits_termsuse_guard();
DROP FUNCTION deposits_depositterms_guard();
DROP FUNCTION deposits_deposit_guard();
DROP FUNCTION deposits_mtatemplate_guard();
DROP FUNCTION deposits_depositor_guard();
DROP FUNCTION deposits_contact_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("deposits", "0002_row_audit")]

    operations = [migrations.RunSQL(FUNCTIONS, REVERSE)]
