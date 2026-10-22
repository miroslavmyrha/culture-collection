"""Room for the status awaiting_confirmation (#89), 21 characters: varchar(20) becomes
varchar(30).

Ignored by the migration linter on purpose: it flags every ALTER COLUMN, but PostgreSQL widens a
varchar without rewriting the table or its indexes (checked on PostgreSQL 18: the file nodes of
the table and of an index on the column stay the same), and code that reads or writes the column
sees no difference. It holds the table's lock for a moment. Kept apart so the linter still checks
the other migrations of the issue.
"""

from django.db import migrations, models
from django_migration_linter import IgnoreMigration


class Migration(migrations.Migration):
    dependencies = [("distribution", "0005_shipment_audit_and_guards")]

    operations = [
        IgnoreMigration(),
        migrations.AlterField(
            model_name="distributionrequest",
            name="status",
            field=models.CharField(choices=[("submitted", "Submitted"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled"), ("shipped", "Shipped"), ("awaiting_confirmation", "Awaiting confirmation")], default="submitted", max_length=30),
        ),
    ]
