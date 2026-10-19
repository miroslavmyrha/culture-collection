"""Row audit on taxonomy_taxon and taxonomy_taxonidentifier, with the values of
audit.registry.ROW_AUDITED_TABLES. Every column is audited: none is a secret, noise or
personal (an authority is part of a published name)."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("taxonomy", "0001_initial"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("taxonomy_taxon", label="taxonomy.taxon"),
        attach_row_audit("taxonomy_taxonidentifier", label="taxonomy.taxonidentifier"),
    ]
