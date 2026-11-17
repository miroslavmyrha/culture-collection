"""The guard of labs_locationgrant with the confirmation of #267: a grant changes twice at most,
once when a second manager confirms it, once when it is revoked (a proposal is withdrawn the same
way), and never after that. The confirmation is set once, from nothing, by a manager of the lab,
and changes nothing else. The check constraints of 0007 keep the confirmer apart from the
proposer and the holder. The function pins its search_path and reaches the memberships through
TG_TABLE_SCHEMA."""

from django.db import migrations

FUNCTION = r"""
CREATE OR REPLACE FUNCTION labs_locationgrant_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    manager boolean;
    steps CONSTANT text[] := ARRAY['confirmed_at', 'confirmed_by_id', 'revoked_at',
                                   'revoked_by_id', 'revoke_reason', 'updated_at'];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'location grants are revoked, never deleted (grant %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       OR (to_jsonb(NEW) - steps) IS DISTINCT FROM (to_jsonb(OLD) - steps) THEN
        RAISE EXCEPTION 'a location grant changes only when it is confirmed and when it is'
            ' revoked (grant %)', OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF (NEW.confirmed_at, NEW.confirmed_by_id) IS DISTINCT FROM
       (OLD.confirmed_at, OLD.confirmed_by_id) THEN
        IF OLD.confirmed_at IS NOT NULL OR OLD.confirmed_by_id IS NOT NULL
           OR NEW.revoked_at IS NOT NULL THEN
            RAISE EXCEPTION 'a location grant is confirmed once, while open (grant %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.labs_membership m'
            ' WHERE m.lab_id = $1 AND m.user_id = $2 AND m.role = ''manager'')', TG_TABLE_SCHEMA)
            INTO manager USING NEW.lab_id, NEW.confirmed_by_id;
        IF NOT manager THEN
            RAISE EXCEPTION 'a location grant is confirmed by a manager of its lab (grant %)',
                OLD.public_id USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

PREVIOUS = r"""
CREATE OR REPLACE FUNCTION labs_locationgrant_guard() RETURNS trigger
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
"""


class Migration(migrations.Migration):
    dependencies = [("labs", "0007_locationgrant_confirmation")]

    operations = [migrations.RunSQL(FUNCTION, PREVIOUS)]
