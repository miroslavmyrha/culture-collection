"""Row audit and guards of the second factor (#176), with the classes of
audit.registry.ROW_AUDITED_TABLES.

- A security key changes only its sign count (never down), its name and when it was last used.
- A TOTP device changes only its last accepted time step (never down) and when it was used.
- A recovery code is used once: used_at is set from nothing, nothing else changes.
- A factor reset is never deleted and ends once, confirmed or withdrawn. Who proposes is a
  manager of the lab the user belongs to, or a superuser when the reset names no lab; who
  confirms is another person of the same kind, never the proposer or the user (the checks of
  users 0008 hold the last two). Keys, devices and codes may be deleted: the row audit records it.

The functions pin their search_path and reach other tables through TG_TABLE_SCHEMA.
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION users_securitykey_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF (to_jsonb(NEW) - 'sign_count' - 'name' - 'last_used_at' - 'updated_at')
       IS DISTINCT FROM (to_jsonb(OLD) - 'sign_count' - 'name' - 'last_used_at' - 'updated_at')
       OR NEW.sign_count < OLD.sign_count THEN
        RAISE EXCEPTION 'a security key changes only its name, its use and a higher sign count'
            ' (key %)', OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER users_securitykey_guard BEFORE UPDATE ON users_securitykey
    FOR EACH ROW EXECUTE FUNCTION users_securitykey_guard();

CREATE FUNCTION users_totpdevice_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF (to_jsonb(NEW) - 'last_step' - 'last_used_at') IS DISTINCT FROM
       (to_jsonb(OLD) - 'last_step' - 'last_used_at')
       OR NEW.last_step < OLD.last_step THEN
        RAISE EXCEPTION 'a TOTP device changes only its last accepted step, never back (user %)',
            OLD.user_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER users_totpdevice_guard BEFORE UPDATE ON users_totpdevice
    FOR EACH ROW EXECUTE FUNCTION users_totpdevice_guard();

CREATE FUNCTION users_recoverycode_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF OLD.used_at IS NOT NULL OR NEW.used_at IS NULL
       OR (to_jsonb(NEW) - 'used_at') IS DISTINCT FROM (to_jsonb(OLD) - 'used_at') THEN
        RAISE EXCEPTION 'a recovery code is used once and changes nothing else (code %)', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER users_recoverycode_guard BEFORE UPDATE ON users_recoverycode
    FOR EACH ROW EXECUTE FUNCTION users_recoverycode_guard();

-- May `person` decide a reset in `lab`: a manager of it, or a superuser when there is no lab.
CREATE FUNCTION users_factorreset_decider(schema text, lab bigint, person bigint, member bigint)
    RETURNS boolean
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    allowed boolean;
BEGIN
    IF lab IS NULL THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.users_user u'
            ' WHERE u.id = $1 AND u.is_superuser AND u.is_active)', schema)
            INTO allowed USING person;
        RETURN allowed;
    END IF;
    EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.labs_membership m'
        ' WHERE m.lab_id = $1 AND m.user_id = $2 AND m.role = ''manager'')'
        ' AND EXISTS (SELECT FROM %1$I.labs_membership m'
        ' WHERE m.lab_id = $1 AND m.user_id = $3)', schema)
        INTO allowed USING lab, person, member;
    RETURN allowed;
END;
$$;

CREATE FUNCTION users_factorreset_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    steps CONSTANT text[] := ARRAY['confirmed_by_id', 'confirmed_at', 'confirm_reason',
                                   'withdrawn_by_id', 'withdrawn_at', 'withdraw_reason',
                                   'updated_at'];
    decider CONSTANT text := format('SELECT %1$I.users_factorreset_decider($1, $2, $3, $4)',
                                    TG_TABLE_SCHEMA);
    allowed boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'factor resets are confirmed or withdrawn, never deleted (reset %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        EXECUTE decider INTO allowed
            USING TG_TABLE_SCHEMA::text, NEW.lab_id, NEW.proposed_by_id, NEW.user_id;
        IF NEW.confirmed_at IS NOT NULL OR NEW.withdrawn_at IS NOT NULL OR NOT allowed THEN
            RAISE EXCEPTION 'a factor reset is proposed open, by a manager of a lab of the user'
                ' or by a superuser (reset %)', NEW.public_id USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.confirmed_at IS NOT NULL OR OLD.withdrawn_at IS NOT NULL
       OR (to_jsonb(NEW) - steps) IS DISTINCT FROM (to_jsonb(OLD) - steps) THEN
        RAISE EXCEPTION 'a factor reset ends once, confirmed or withdrawn (reset %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.confirmed_by_id IS NOT NULL THEN
        EXECUTE decider INTO allowed
            USING TG_TABLE_SCHEMA::text, NEW.lab_id, NEW.confirmed_by_id, NEW.user_id;
    END IF;
    IF NEW.confirmed_by_id IS NOT NULL AND NOT allowed THEN
        RAISE EXCEPTION 'a factor reset is confirmed by a manager of its lab, or a superuser'
            ' when it names none (reset %)', OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.withdrawn_by_id IS NOT NULL THEN
        EXECUTE decider INTO allowed
            USING TG_TABLE_SCHEMA::text, NEW.lab_id, NEW.withdrawn_by_id, NEW.user_id;
    END IF;
    IF NEW.withdrawn_by_id IS NOT NULL AND NOT allowed THEN
        RAISE EXCEPTION 'a factor reset is withdrawn by a manager of its lab, or a superuser'
            ' when it names none (reset %)', OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER users_factorreset_guard BEFORE INSERT OR UPDATE OR DELETE ON users_factorreset
    FOR EACH ROW EXECUTE FUNCTION users_factorreset_guard();
"""

REVERSE = """
DROP TRIGGER users_factorreset_guard ON users_factorreset;
DROP FUNCTION users_factorreset_guard();
DROP FUNCTION users_factorreset_decider(text, bigint, bigint, bigint);
DROP TRIGGER users_recoverycode_guard ON users_recoverycode;
DROP FUNCTION users_recoverycode_guard();
DROP TRIGGER users_totpdevice_guard ON users_totpdevice;
DROP FUNCTION users_totpdevice_guard();
DROP TRIGGER users_securitykey_guard ON users_securitykey;
DROP FUNCTION users_securitykey_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0008_second_factor"),
        ("audit", "0043_validate_reason_required_factor_reset"),
    ]

    operations = [
        attach_row_audit(
            "users_securitykey",
            label="users.securitykey",
            exclude=("last_used_at",),
            secret=("credential_id", "public_key"),
        ),
        attach_row_audit(
            "users_totpdevice",
            label="users.totpdevice",
            exclude=("last_step", "last_used_at"),
            secret=("secret",),
        ),
        attach_row_audit(
            "users_recoverycode", label="users.recoverycode", secret=("code_hash",)
        ),
        attach_row_audit("users_factorreset", label="users.factorreset"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
