"""The actor's own index on the audit events goes (#42): audit_event_actor_time_idx
(actor, -occurred_at) leads with the same column and serves every lookup and the foreign key.

Dropped CONCURRENTLY, so writes to the audit table are not locked, hence atomic = False and a
migration of its own; IF EXISTS makes a rerun after an interruption safe. The reverse builds it
again the same way.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

INDEX = "audit_auditevent_actor_id_270bb4b7"


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("audit", "0045_validate_reason_required_enrolment_code"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}",
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON audit_auditevent (actor_id)",
                )
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="auditevent",
                    name="actor",
                    field=models.ForeignKey(
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                )
            ],
        ),
    ]
