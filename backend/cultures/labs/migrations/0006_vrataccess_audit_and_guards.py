"""Row audit on labs_vrataccess (every column audited, audit.registry.ROW_AUDITED_TABLES) and its
guards against every writer: QuerySet.update(), raw SQL, psql (act 281/2002 Sb., § 14a(4), ADR
0009, amendment of 2026-11-03). Who was on the lab's VRAT access list, and when, stays readable.

- labs_vrataccess: never deleted. An entry starts open, for a user who is active and a member of
  the lab when it is written. It changes once, when it ends (ended_at, ended_by, end_reason;
  updated_at may change), and never again: an ended entry is not reopened, a new one is a new row.
- The other direction, at commit (deferred constraint triggers): an account that became inactive
  holds no open entry, and a membership that is gone leaves no open entry in its lab. The
  services end the entries before they deactivate the account or delete the membership, so these
  hold also in a session that set its constraints immediate. A constraint trigger fires only for
  rows written after it exists.

The functions pin their search_path and reach other tables through TG_TABLE_SCHEMA. The runtime
role has SELECT, INSERT and UPDATE (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION labs_vrataccess_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    member boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'VRAT access entries are ended, never deleted (entry %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.users_user u'
            ' JOIN %1$I.labs_membership m ON m.user_id = u.id'
            ' WHERE u.id = $1 AND u.is_active AND m.lab_id = $2)', TG_TABLE_SCHEMA)
            INTO member USING NEW.user_id, NEW.lab_id;
        IF NEW.ended_at IS NOT NULL OR NOT member THEN
            RAISE EXCEPTION 'a VRAT access entry starts open, for an active member of its lab (entry %)',
                NEW.public_id USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.ended_at IS NOT NULL
       OR (to_jsonb(NEW) - 'ended_at' - 'ended_by_id' - 'end_reason' - 'updated_at')
          IS DISTINCT FROM
          (to_jsonb(OLD) - 'ended_at' - 'ended_by_id' - 'end_reason' - 'updated_at') THEN
        RAISE EXCEPTION 'a VRAT access entry changes only once, when it ends (entry %)',
            OLD.public_id USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION labs_vrataccess_holder_deactivated() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    left_open boolean;
BEGIN
    -- The rows as committed now, not as this queued event saw them.
    EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.users_user u'
        ' JOIN %1$I.labs_vrataccess a ON a.user_id = u.id'
        ' WHERE u.id = $1 AND NOT u.is_active AND a.ended_at IS NULL)', TG_TABLE_SCHEMA)
        INTO left_open USING NEW.id;
    IF left_open THEN
        RAISE EXCEPTION 'an inactive account holds no open VRAT access entry (user %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION labs_vrataccess_member_left() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    left_open boolean;
BEGIN
    EXECUTE format('SELECT EXISTS (SELECT FROM %1$I.labs_vrataccess a'
        ' WHERE a.lab_id = $1 AND a.user_id = $2 AND a.ended_at IS NULL)'
        ' AND NOT EXISTS (SELECT FROM %1$I.labs_membership m'
        ' WHERE m.lab_id = $1 AND m.user_id = $2)', TG_TABLE_SCHEMA)
        INTO left_open USING OLD.lab_id, OLD.user_id;
    IF left_open THEN
        RAISE EXCEPTION 'a person who left the lab holds no open VRAT access entry there (membership %)',
            OLD.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION labs_vrataccess_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION labs_vrataccess_holder_deactivated() FROM PUBLIC;
REVOKE ALL ON FUNCTION labs_vrataccess_member_left() FROM PUBLIC;

CREATE TRIGGER labs_vrataccess_guard BEFORE INSERT OR UPDATE OR DELETE ON labs_vrataccess
    FOR EACH ROW EXECUTE FUNCTION labs_vrataccess_guard();
CREATE CONSTRAINT TRIGGER labs_vrataccess_holder_deactivated
    AFTER UPDATE OF is_active ON users_user DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (OLD.is_active AND NOT NEW.is_active)
    EXECUTE FUNCTION labs_vrataccess_holder_deactivated();
CREATE CONSTRAINT TRIGGER labs_vrataccess_member_left
    AFTER DELETE ON labs_membership DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION labs_vrataccess_member_left();
"""

REVERSE = """
DROP TRIGGER labs_vrataccess_member_left ON labs_membership;
DROP TRIGGER labs_vrataccess_holder_deactivated ON users_user;
DROP TRIGGER labs_vrataccess_guard ON labs_vrataccess;
DROP FUNCTION labs_vrataccess_member_left();
DROP FUNCTION labs_vrataccess_holder_deactivated();
DROP FUNCTION labs_vrataccess_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0005_vrataccess"),
        ("users", "0007_user_erased_at"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("labs_vrataccess", label="labs.vrataccess"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
