"""Row audit and the trigger of the finding decisions (#263), against every writer.

- distribution_findingdecision: never changed or deleted; inserted only for a request that is
  submitted (its approval) or approved (a second approval), by a member of the request's lab.

The function pins its search_path and reaches other tables through TG_TABLE_SCHEMA. The runtime
role has SELECT and INSERT on the table (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION distribution_findingdecision_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    request_status text;
    member boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a decision of a finding never changes (request %)', OLD.request_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT r.status, EXISTS (SELECT FROM %1$I.labs_membership m'
        ' WHERE m.lab_id = r.lab_id AND m.user_id = $2)'
        ' FROM %1$I.distribution_distributionrequest r WHERE r.id = $1', TG_TABLE_SCHEMA)
        INTO request_status, member USING NEW.request_id, NEW.decided_by_id;
    IF request_status IS DISTINCT FROM 'submitted' AND request_status IS DISTINCT FROM 'approved' THEN
        RAISE EXCEPTION 'a finding is decided at an approval (request %, status %)',
            NEW.request_id, request_status USING ERRCODE = 'check_violation';
    END IF;
    IF NOT member THEN
        RAISE EXCEPTION 'a finding is decided by a member of the request''s lab (request %)',
            NEW.request_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION distribution_findingdecision_guard() FROM PUBLIC;

CREATE TRIGGER distribution_findingdecision_guard
    BEFORE INSERT OR UPDATE OR DELETE ON distribution_findingdecision
    FOR EACH ROW EXECUTE FUNCTION distribution_findingdecision_guard();
"""

REVERSE = """
DROP TRIGGER distribution_findingdecision_guard ON distribution_findingdecision;
DROP FUNCTION distribution_findingdecision_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("distribution", "0019_finding_decision")]

    operations = [
        attach_row_audit("distribution_findingdecision", label="distribution.findingdecision"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
