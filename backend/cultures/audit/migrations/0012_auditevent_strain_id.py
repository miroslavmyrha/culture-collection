"""The strain timeline root on service events (ADR 0008, D13).

Additive: a nullable column without a default, so PostgreSQL changes only the
catalog and rewrites no row. It comes before the strain table and before the
first strain event, so no event ever needs a backfill. The index is 0013.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("audit", "0011_reason_required_user_erased")]

    operations = [
        migrations.AddField(
            model_name="auditevent",
            name="strain_id",
            field=models.UUIDField(blank=True, null=True),
        ),
    ]
