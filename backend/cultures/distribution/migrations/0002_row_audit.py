"""Row audit on every distribution table (audit.registry.ROW_AUDITED_TABLES): the same labels
and classes as the registry, which the invariants compare with pg_trigger."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("distribution", "0001_initial"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("distribution_requester", label="distribution.requester"),
        attach_row_audit(
            "distribution_document", label="distribution.document", exclude=("content",)
        ),
        attach_row_audit("distribution_recipientpermit", label="distribution.recipientpermit"),
        attach_row_audit(
            "distribution_distributionrequest", label="distribution.distributionrequest"
        ),
        attach_row_audit("distribution_requestcounter", label="distribution.requestcounter"),
        attach_row_audit("distribution_requestline", label="distribution.requestline"),
        attach_row_audit("distribution_linepermit", label="distribution.linepermit"),
        attach_row_audit("distribution_mtaacceptance", label="distribution.mtaacceptance"),
        attach_row_audit("distribution_vialreservation", label="distribution.vialreservation"),
    ]
