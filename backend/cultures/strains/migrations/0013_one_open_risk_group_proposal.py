"""One open proposal to lower a risk group per strain, built without locking writes.

A partial unique index: only the proposals that are neither confirmed nor withdrawn are in it,
so confirmed ones pile up on a strain whose group was lowered more than once. CREATE UNIQUE
INDEX CONCURRENTLY cannot run in a transaction, hence atomic = False and a migration of its own,
and Django has no operation for a unique index, hence the SQL with the constraint kept in the
model state. If it is interrupted, PostgreSQL leaves an INVALID index: drop it
(DROP INDEX CONCURRENTLY strains_riskgroupproposal_one_open) and migrate again.
"""

from django.db import migrations, models

NAME = "strains_riskgroupproposal_one_open"

FORWARD = f"""
CREATE UNIQUE INDEX CONCURRENTLY {NAME} ON strains_riskgroupproposal (strain_id)
    WHERE (confirmed_at IS NULL AND withdrawn_at IS NULL);
"""

REVERSE = f"DROP INDEX CONCURRENTLY {NAME};"


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("strains", "0012_risk_group_proposal")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(FORWARD, REVERSE)],
            state_operations=[
                migrations.AddConstraint(
                    model_name="riskgroupproposal",
                    constraint=models.UniqueConstraint(
                        fields=["strain"],
                        condition=models.Q(
                            confirmed_at__isnull=True, withdrawn_at__isnull=True
                        ),
                        name=NAME,
                    ),
                ),
            ],
        ),
    ]
