"""The strain timeline index, built without locking writes to the audit table.

Partial: only events that name a strain are in it. CREATE INDEX CONCURRENTLY
cannot run in a transaction, hence atomic = False and a migration of its own.
If it is interrupted, PostgreSQL leaves an INVALID index: drop it (DROP INDEX
CONCURRENTLY audit_event_strain_time_idx) and migrate again.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("audit", "0012_auditevent_strain_id")]

    operations = [
        AddIndexConcurrently(
            model_name="auditevent",
            index=models.Index(
                fields=["lab", "strain_id", "-occurred_at"],
                name="audit_event_strain_time_idx",
                condition=Q(strain_id__isnull=False),
            ),
        ),
    ]
