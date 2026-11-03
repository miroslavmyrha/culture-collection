"""Row audit and trigger of the loss report (#159), against every writer: QuerySet.update(), raw
SQL, psql (ADR 0009, amendment of 2026-11-02).

- lineage_viallossreport: never changed or deleted. On insert: its vial is of its lab, lost, and
  went lost at `lost_at` (the vial's status_changed_at, so the report is of the loss the vial is
  in); a cz_vrat or cz_rat restriction of the vial's strain was in force at that moment (created
  at or before it, not ended by then); the report is not dated before the Czech day of the loss.
  The restriction rule is written twice: here, and in lineage.selectors.reportable_loss, which
  the service and Home read; tests/test_loss_reports.py builds every kind and an ended
  restriction and asserts that both agree.

The runtime role has SELECT and INSERT (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION lineage_viallossreport_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    vial_lab bigint;
    vial_status text;
    vial_changed timestamptz;
    vial_strain bigint;
    listed boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a loss report never changes (report %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT v.lab_id, v.status, v.status_changed_at, b.strain_id'
        ' FROM %1$I.lineage_vial v JOIN %1$I.lineage_batch b ON b.id = v.batch_id'
        ' WHERE v.id = $1', TG_TABLE_SCHEMA)
        INTO vial_lab, vial_status, vial_changed, vial_strain USING NEW.vial_id;
    IF vial_lab IS DISTINCT FROM NEW.lab_id OR vial_status IS DISTINCT FROM 'lost'
       OR vial_changed IS DISTINCT FROM NEW.lost_at THEN
        RAISE EXCEPTION 'a loss report is of a lost vial of its lab, for the loss it is in (report %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    EXECUTE format('SELECT EXISTS (SELECT FROM %I.strains_strainrestriction r'
        ' WHERE r.strain_id = $1 AND r.kind IN (''cz_vrat'', ''cz_rat'')'
        ' AND r.created_at <= $2 AND (r.ended_at IS NULL OR r.ended_at > $2))', TG_TABLE_SCHEMA)
        INTO listed USING vial_strain, NEW.lost_at;
    IF NOT listed THEN
        RAISE EXCEPTION 'a loss is reported only for a strain that was a VRAT or RAT when the vial was lost (report %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.reported_on < (NEW.lost_at AT TIME ZONE 'Europe/Prague')::date THEN
        RAISE EXCEPTION 'a loss report is not dated before the loss (report %)', NEW.public_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION lineage_viallossreport_guard() FROM PUBLIC;

CREATE TRIGGER lineage_viallossreport_guard
    BEFORE INSERT OR UPDATE OR DELETE ON lineage_viallossreport
    FOR EACH ROW EXECUTE FUNCTION lineage_viallossreport_guard();
"""

REVERSE = """
DROP TRIGGER lineage_viallossreport_guard ON lineage_viallossreport;
DROP FUNCTION lineage_viallossreport_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("lineage", "0011_vial_loss_report"),
        ("strains", "0010_confirmed_proposal_outcome"),
    ]

    operations = [
        attach_row_audit("lineage_viallossreport", label="lineage.viallossreport"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
