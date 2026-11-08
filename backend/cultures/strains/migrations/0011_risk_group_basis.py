"""The basis of a strain's risk group and the time it was set (#174).

Three steps on the existing table: two nullable or defaulted columns and the check that ties
them to each other. The proposal table that a lowering needs is 0012, its triggers 0013.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("strains", "0010_confirmed_proposal_outcome")]

    operations = [
        migrations.AddField(
            model_name='strain',
            name='risk_group_basis',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.AddField(
            model_name='strain',
            name='risk_group_set_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='strain',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('risk_group_basis', ''), ('risk_group_set_at__isnull', True)), models.Q(('risk_group_basis__regex', '\\S'), ('risk_group_set_at__isnull', False)), _connector='OR'), name='strains_strain_risk_group_basis_with_time'),
        ),
    ]
