"""Row audit on labs_lab and labs_membership, with the values of
audit.registry.ROW_AUDITED_TABLES. Every column is audited: none is a secret or noise.
"""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0001_initial"),
        ("audit", "0003_row_change_function"),
    ]

    operations = [
        attach_row_audit("labs_lab", label="labs.lab"),
        attach_row_audit("labs_membership", label="labs.membership"),
    ]
