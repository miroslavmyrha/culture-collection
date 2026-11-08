"""A third transport class, UN 3245, for a request with a GMO line, with the one basis that
states why it goes there (#173).

The check of a package takes a third pair; the two it held keep their bases, so every row
written before this migration passes it. The choices of the two columns gain the new values.
What the class rests on, and why a GMO is never exempt: ADR 0009 and 0008, amendments of
2026-11-04, and docs/compliance.md, R-SHIP-02.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0005_contact_phone'),
        ('distribution', '0014_rat_notice_names_its_agents'),
        ('labs', '0006_vrataccess_audit_and_guards'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='shipment',
            name='distribution_shipment_class_and_basis',
        ),
        migrations.RemoveConstraint(
            model_name='shipmentpreparation',
            name='distribution_shipmentpreparation_class_and_basis',
        ),
        migrations.AlterField(
            model_name='shipment',
            name='classification_basis',
            field=models.CharField(choices=[('exempt_non_pathogenic', 'Exempt: not pathogenic to humans or animals'), ('exempt_inactivated', 'Exempt: neutralised or inactivated'), ('indicative_list', 'Not on the indicative list of Category A'), ('professional_judgement', 'Professional judgement'), ('gmo_not_infectious', 'A genetically modified micro-organism that is not an infectious substance')], max_length=30),
        ),
        migrations.AlterField(
            model_name='shipment',
            name='transport_class',
            field=models.CharField(choices=[('not_subject', 'Not subject to the dangerous goods rules (exempt)'), ('un3373', 'UN 3373, Biological substance, Category B'), ('un3245', 'UN 3245, Genetically modified micro-organisms')], max_length=20),
        ),
        migrations.AlterField(
            model_name='shipmentpreparation',
            name='classification_basis',
            field=models.CharField(choices=[('exempt_non_pathogenic', 'Exempt: not pathogenic to humans or animals'), ('exempt_inactivated', 'Exempt: neutralised or inactivated'), ('indicative_list', 'Not on the indicative list of Category A'), ('professional_judgement', 'Professional judgement'), ('gmo_not_infectious', 'A genetically modified micro-organism that is not an infectious substance')], max_length=30),
        ),
        migrations.AlterField(
            model_name='shipmentpreparation',
            name='transport_class',
            field=models.CharField(choices=[('not_subject', 'Not subject to the dangerous goods rules (exempt)'), ('un3373', 'UN 3373, Biological substance, Category B'), ('un3245', 'UN 3245, Genetically modified micro-organisms')], max_length=20),
        ),
        migrations.AddConstraint(
            model_name='shipment',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('classification_basis__in', frozenset(['exempt_inactivated', 'exempt_non_pathogenic'])), ('transport_class', 'not_subject')), models.Q(('classification_basis__in', frozenset(['indicative_list', 'professional_judgement'])), ('transport_class', 'un3373')), models.Q(('classification_basis__in', frozenset(['gmo_not_infectious'])), ('transport_class', 'un3245')), _connector='OR'), name='distribution_shipment_class_and_basis'),
        ),
        migrations.AddConstraint(
            model_name='shipmentpreparation',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('classification_basis__in', frozenset(['exempt_inactivated', 'exempt_non_pathogenic'])), ('transport_class', 'not_subject')), models.Q(('classification_basis__in', frozenset(['indicative_list', 'professional_judgement'])), ('transport_class', 'un3373')), models.Q(('classification_basis__in', frozenset(['gmo_not_infectious'])), ('transport_class', 'un3245')), _connector='OR'), name='distribution_shipmentpreparation_class_and_basis'),
        ),
    ]
