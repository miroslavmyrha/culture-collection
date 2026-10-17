"""The lab timeline index, built without locking writes to the audit table.

CREATE INDEX CONCURRENTLY cannot run in a transaction, hence atomic = False and a
migration of its own. If it is interrupted, PostgreSQL leaves an INVALID index:
drop it (DROP INDEX CONCURRENTLY audit_event_lab_time_idx) and migrate again.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("audit", "0004_auditevent_lab")]

    operations = [
        AddIndexConcurrently(
            model_name="auditevent",
            index=models.Index(fields=["lab", "-occurred_at"], name="audit_event_lab_time_idx"),
        ),
    ]
