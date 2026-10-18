"""Row audit on biosafety_labauthorisation, with the values of
audit.registry.ROW_AUDITED_TABLES. Every column is audited."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("biosafety", "0001_initial"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("biosafety_labauthorisation", label="biosafety.labauthorisation"),
    ]
