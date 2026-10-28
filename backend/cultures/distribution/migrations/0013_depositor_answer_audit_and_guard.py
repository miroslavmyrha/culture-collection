"""Row audit and trigger of the depositor's answer (#144), against every writer: QuerySet.update(),
raw SQL, psql (ADR 0008, amendment of 2026-10-28).

- distribution_depositoranswer: never changed or deleted. On insert: its line, the line's request
  and its document (if any) are of its lab, the request waits for a decision (submitted), and the
  terms version the line pinned leave the request's use on request to the depositor. That last
  rule is written twice: here, and in distribution.services.depositor_answer_record (the
  `not_on_request` refusal); tests/test_depositor_answer.py builds every decision a terms use may
  have and asserts that both agree (ADR 0010, proposed).

The runtime role has SELECT and INSERT (audit.roles).
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit

FUNCTIONS = r"""
CREATE FUNCTION distribution_depositoranswer_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    line_lab bigint;
    request_lab bigint;
    request_status text;
    decision text;
    document_lab bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a depositor''s answer never changes (answer %)', OLD.public_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    EXECUTE format('SELECT l.lab_id, r.lab_id, r.status, u.decision'
        ' FROM %1$I.distribution_requestline l'
        ' JOIN %1$I.distribution_distributionrequest r ON r.id = l.request_id'
        ' LEFT JOIN %1$I.deposits_termsuse u ON u.terms_id = l.terms_id AND u.use = r.use'
        ' WHERE l.id = $1', TG_TABLE_SCHEMA)
        INTO line_lab, request_lab, request_status, decision USING NEW.line_id;
    IF NEW.document_id IS NOT NULL THEN
        EXECUTE format('SELECT lab_id FROM %I.distribution_document WHERE id = $1', TG_TABLE_SCHEMA)
            INTO document_lab USING NEW.document_id;
    END IF;
    IF line_lab IS DISTINCT FROM NEW.lab_id OR request_lab IS DISTINCT FROM NEW.lab_id
       OR (NEW.document_id IS NOT NULL AND document_lab IS DISTINCT FROM NEW.lab_id)
       OR request_status IS DISTINCT FROM 'submitted' THEN
        RAISE EXCEPTION 'an answer is recorded on a line of a waiting request of its lab (answer %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    IF decision IS DISTINCT FROM 'on_request' THEN
        RAISE EXCEPTION 'an answer is recorded only where the pinned terms leave the use on request to the depositor (answer %)',
            NEW.public_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION distribution_depositoranswer_guard() FROM PUBLIC;

CREATE TRIGGER distribution_depositoranswer_guard
    BEFORE INSERT OR UPDATE OR DELETE ON distribution_depositoranswer
    FOR EACH ROW EXECUTE FUNCTION distribution_depositoranswer_guard();
"""

REVERSE = """
DROP TRIGGER distribution_depositoranswer_guard ON distribution_depositoranswer;
DROP FUNCTION distribution_depositoranswer_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("deposits", "0005_contact_phone"),
        ("distribution", "0012_depositor_answer"),
    ]

    operations = [
        attach_row_audit("distribution_depositoranswer", label="distribution.depositoranswer"),
        migrations.RunSQL(FUNCTIONS, REVERSE),
    ]
