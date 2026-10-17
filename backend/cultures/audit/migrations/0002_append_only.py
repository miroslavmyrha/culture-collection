"""Audit rows can never be changed or deleted, not even through raw SQL or psql.

- UPDATE and DELETE: a row trigger raises for every role, the owner included.
- TRUNCATE fires no row trigger, so a statement trigger refuses it for every
  role that is not the table owner (or a member of the owning role). The owner
  is let through because Django's flush, run after each transactional test
  (pytest transaction=True, TransactionTestCase), truncates every table in one
  statement as the owner. The owner can drop the trigger anyway, so refusing
  it would protect nothing. In production the app role owns nothing and has no
  TRUNCATE grant, so the grant refuses it first (tests/test_append_only.py).
"""

from django.db import migrations

FORWARD = """
CREATE FUNCTION audit_refuse_change() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % refused', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;
CREATE FUNCTION audit_refuse_truncate() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF NOT pg_has_role(current_user, (SELECT relowner FROM pg_class WHERE oid = TG_RELID), 'USAGE')
    THEN
        RAISE EXCEPTION '% is append-only: TRUNCATE by % refused', TG_TABLE_NAME, current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION audit_refuse_change() FROM PUBLIC;
REVOKE ALL ON FUNCTION audit_refuse_truncate() FROM PUBLIC;
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_refuse_change();
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_rowchange
    FOR EACH ROW EXECUTE FUNCTION audit_refuse_change();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_rowchange
    FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();
"""

REVERSE = """
DROP TRIGGER audit_no_truncate ON audit_rowchange;
DROP TRIGGER audit_no_truncate ON audit_auditevent;
DROP TRIGGER audit_append_only ON audit_rowchange;
DROP TRIGGER audit_append_only ON audit_auditevent;
DROP FUNCTION audit_refuse_truncate();
DROP FUNCTION audit_refuse_change();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
