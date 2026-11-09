"""A risk group may rest on the entry of the official list it was read in (#169).

One nullable foreign key on the strain and one on the proposal to lower a group, neither with an
index: the entry is read from the row, never the row from the entry, and an index would lock the
tables while it is built. The CHECK says only that an entry comes with words; which entry may be
named, and that every group recorded from now on states its basis, are the guards of migration
0018, because a CHECK reads no other table. Rows written before this keep the empty basis they
have: no basis is invented after the fact (R-RISK-07).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('biosafety', '0006_official_lists'),
        ('strains', '0016_restriction_list_entry_guards'),
    ]

    operations = [
        migrations.AddField(
            model_name='riskgroupproposal',
            name='basis_entry',
            field=models.ForeignKey(blank=True, db_index=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='biosafety.regulatorylistentry'),
        ),
        migrations.AddField(
            model_name='strain',
            name='risk_group_entry',
            field=models.ForeignKey(blank=True, db_index=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='biosafety.regulatorylistentry'),
        ),
        migrations.AddConstraint(
            model_name='strain',
            constraint=models.CheckConstraint(condition=models.Q(('risk_group_entry__isnull', True), models.Q(('risk_group_basis__regex', '\\S'), ('risk_group_entry__isnull', False)), _connector='OR'), name='strains_strain_risk_group_entry_with_basis'),
        ),
    ]
