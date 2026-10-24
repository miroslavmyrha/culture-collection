"""Validates the reason constraint 0022 added NOT VALID, in a transaction of its own: VALIDATE
takes SHARE UPDATE EXCLUSIVE, so services keep writing events while the rows are checked."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("audit", "0022_reason_required_restriction_end")]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE audit_auditevent VALIDATE CONSTRAINT audit_auditevent_reason_required;",
            migrations.RunSQL.noop,
        ),
    ]
