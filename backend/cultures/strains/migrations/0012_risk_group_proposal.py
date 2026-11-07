"""The table a two-person lowering of a risk group is proposed in (#174).

Its one open proposal per strain is a partial unique index, built without locking writes in
0013; its triggers and row audit are in 0014.
"""


import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('labs', '0006_vrataccess_audit_and_guards'),
        ('strains', '0011_risk_group_basis'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RiskGroupProposal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('risk_group', models.PositiveSmallIntegerField()),
                ('from_risk_group', models.PositiveSmallIntegerField()),
                ('basis', models.TextField()),
                ('reason', models.TextField()),
                ('proposed_at', models.DateTimeField()),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('withdrawn_at', models.DateTimeField(blank=True, null=True)),
                ('withdraw_reason', models.TextField(blank=True)),
                ('confirmed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('lab', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='labs.lab')),
                ('proposed_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('strain', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='risk_group_proposals', to='strains.strain')),
                ('withdrawn_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'abstract': False,
                'constraints': [models.UniqueConstraint(fields=('public_id',), name='strains_riskgroupproposal_public_id_uniq'), models.CheckConstraint(condition=models.Q(('from_risk_group__lte', 4), ('risk_group__gte', 1), ('risk_group__lt', models.F('from_risk_group'))), name='strains_riskgroupproposal_lowers'), models.CheckConstraint(condition=models.Q(('basis__regex', '\\S')), name='strains_riskgroupproposal_basis_given'), models.CheckConstraint(condition=models.Q(('reason__regex', '\\S')), name='strains_riskgroupproposal_reason_given'), models.CheckConstraint(condition=models.Q(models.Q(('confirmed_at__isnull', True), ('confirmed_by__isnull', True)), models.Q(('confirmed_at__isnull', False), ('confirmed_by__isnull', False)), _connector='OR'), name='strains_riskgroupproposal_confirmation_complete'), models.CheckConstraint(condition=models.Q(models.Q(('withdraw_reason', ''), ('withdrawn_at__isnull', True), ('withdrawn_by__isnull', True)), models.Q(('withdraw_reason__regex', '\\S'), ('withdrawn_at__isnull', False), ('withdrawn_by__isnull', False)), _connector='OR'), name='strains_riskgroupproposal_withdrawal_complete'), models.CheckConstraint(condition=models.Q(('confirmed_at__isnull', True), ('withdrawn_at__isnull', True), _connector='OR'), name='strains_riskgroupproposal_confirmed_or_withdrawn'), models.CheckConstraint(condition=models.Q(('confirmed_by__isnull', True), models.Q(('confirmed_by', models.F('proposed_by')), _negated=True), _connector='OR'), name='strains_riskgroupproposal_second_person'), models.CheckConstraint(condition=models.Q(models.Q(('confirmed_at__isnull', True), ('confirmed_at__gte', models.F('proposed_at')), _connector='OR'), models.Q(('withdrawn_at__isnull', True), ('withdrawn_at__gte', models.F('proposed_at')), _connector='OR')), name='strains_riskgroupproposal_outcome_after_proposal')],
            },
        ),
    ]
