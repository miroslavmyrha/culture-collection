"""Row audit on labs_locationgrant (every column audited, audit.registry.ROW_AUDITED_TABLES),
and a guard trigger: a grant is never deleted, and changes once, when it is revoked. Who
holds the right to see regulated locations, and who held it, stays readable (ADR 0009,
amendment of 2026-10-19). updated_at may change."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION labs_locationgrant_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'location grants are revoked, never deleted (grant %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       OR (to_jsonb(NEW) - 'revoked_at' - 'revoked_by_id' - 'revoke_reason' - 'updated_at')
          IS DISTINCT FROM
          (to_jsonb(OLD) - 'revoked_at' - 'revoked_by_id' - 'revoke_reason' - 'updated_at') THEN
        RAISE EXCEPTION 'a location grant changes only once, when it is revoked (grant %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION labs_locationgrant_guard() FROM PUBLIC;

CREATE TRIGGER labs_locationgrant_guard BEFORE UPDATE OR DELETE ON labs_locationgrant
    FOR EACH ROW EXECUTE FUNCTION labs_locationgrant_guard();
"""

REVERSE = """
DROP TRIGGER labs_locationgrant_guard ON labs_locationgrant;
DROP FUNCTION labs_locationgrant_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0003_locationgrant"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("labs_locationgrant", label="labs.locationgrant"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
