"""The partial index on the medium of a passage, built without locking writes to the table.

Partial: only rows that name a medium are in it. CREATE INDEX CONCURRENTLY cannot run in a
transaction, hence atomic = False and a migration of its own. If it is interrupted, PostgreSQL
leaves an INVALID index: drop it (DROP INDEX CONCURRENTLY passage_growth_medium_idx) and migrate again.
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("lineage", "0007_passage_growth_conditions")]

    operations = [
        AddIndexConcurrently(
            model_name="passage",
            index=models.Index(
                fields=["growth_medium"],
                name="passage_growth_medium_idx",
                condition=Q(growth_medium__isnull=False),
            ),
        ),
    ]
