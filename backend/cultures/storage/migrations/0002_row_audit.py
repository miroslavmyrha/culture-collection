"""Row audit on the storage tables, with the values of audit.registry.ROW_AUDITED_TABLES.
Every column is audited."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("storage", "0001_initial"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("storage_boxtype", label="storage.boxtype"),
        attach_row_audit("storage_storageunit", label="storage.storageunit"),
    ]
