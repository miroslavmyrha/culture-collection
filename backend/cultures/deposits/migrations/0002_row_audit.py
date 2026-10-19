"""Row audit on the deposit tables, with the values of audit.registry.ROW_AUDITED_TABLES.
Every column is audited. deposits_contact is not watched: it holds personal data
(ADR 0008, D11, audit.registry.NOT_ROW_AUDITED)."""

from django.db import migrations

from cultures.audit.operations import attach_row_audit


class Migration(migrations.Migration):
    dependencies = [
        ("deposits", "0001_initial"),
        ("audit", "0010_row_change_personal_marker"),
    ]

    operations = [
        attach_row_audit("deposits_depositor", label="deposits.depositor"),
        attach_row_audit("deposits_mtatemplate", label="deposits.mtatemplate"),
        attach_row_audit("deposits_deposit", label="deposits.deposit"),
        attach_row_audit("deposits_depositterms", label="deposits.depositterms"),
        attach_row_audit("deposits_termsuse", label="deposits.termsuse"),
    ]
