"""Row audit and guard of the enrolment codes (#176), with the classes of
audit.registry.ROW_AUDITED_TABLES: a code is issued by a manager of a lab the user belongs to,
or by a superuser when it names no lab (users_factorreset_decider of 0009), it is never deleted,
and it changes once, when it is used, and only before it expires."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION users_enrolmentcode_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    allowed boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'enrolment codes are used or expire, never deleted (code %)', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        EXECUTE format('SELECT %1$I.users_factorreset_decider($1, $2, $3, $4)', TG_TABLE_SCHEMA)
            INTO allowed USING TG_TABLE_SCHEMA::text, NEW.lab_id, NEW.issued_by_id, NEW.user_id;
        IF NEW.used_at IS NOT NULL OR NOT allowed THEN
            RAISE EXCEPTION 'an enrolment code is issued unused, by a manager of a lab of the'
                ' user or by a superuser' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.used_at IS NOT NULL OR NEW.used_at IS NULL
       OR (to_jsonb(NEW) - 'used_at') IS DISTINCT FROM (to_jsonb(OLD) - 'used_at') THEN
        RAISE EXCEPTION 'an enrolment code is used once and changes nothing else (code %)', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.used_at > OLD.expires_at THEN
        RAISE EXCEPTION 'an enrolment code is used before it expires (code %)', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER users_enrolmentcode_guard BEFORE INSERT OR UPDATE OR DELETE ON users_enrolmentcode
    FOR EACH ROW EXECUTE FUNCTION users_enrolmentcode_guard();
"""

REVERSE = """
DROP TRIGGER users_enrolmentcode_guard ON users_enrolmentcode;
DROP FUNCTION users_enrolmentcode_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0010_enrolment_code"),
        ("audit", "0045_validate_reason_required_enrolment_code"),
    ]

    operations = [
        attach_row_audit(
            "users_enrolmentcode", label="users.enrolmentcode", secret=("code_hash",)
        ),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
