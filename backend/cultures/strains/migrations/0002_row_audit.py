"""Row audit on the four strain tables, with the values of audit.registry.ROW_AUDITED_TABLES.
Every column is audited. The counter's key is its lab."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("strains", "0001_initial"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("strains_strain", label="strains.strain"),
        attach_row_audit("strains_straincounter", label="strains.straincounter", pk=("lab_id",)),
        attach_row_audit("strains_strainidentification", label="strains.strainidentification"),
        attach_row_audit("strains_strainrestriction", label="strains.strainrestriction"),
    ]
