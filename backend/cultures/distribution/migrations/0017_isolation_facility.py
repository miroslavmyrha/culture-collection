"""A recipient records the authorisation of the isolation facility its activity runs in (#197).

Implementing Regulation (EU) 2019/829, Art. 5 c) grants the authorisation of the activity only
where the activity is performed in a quarantine station or confinement facility designated by
the competent authority, and Art. 6(1) issues the Letter of Authority after that authorisation.
So the authorisation is a document of its own, a seventh recipient permit kind. It names no
agents and carries no quantity, category or risk group, so every other constraint of the table
holds for it as written.

The gate that reads it is R-DIST-16, and its database half is migration 0018.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0016_gmo_transport_class'),
        ('labs', '0006_vrataccess_audit_and_guards'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='recipientpermit',
            name='distribution_permit_kind_valid',
        ),
        migrations.AlterField(
            model_name='recipientpermit',
            name='kind',
            field=models.CharField(choices=[('sujb_vrat', 'SÚJB permit to handle highly risky agents (VRAT)'), ('sujb_rat_notice', 'Notice to SÚJB of handling risky agents (RAT)'), ('sujb_exception', 'SÚJB decision allowing a VRAT to a non-holder'), ('plant_health_loa', 'Letter of Authority for a quarantine pest'), ('plant_health_isolation', 'Authorisation of an isolation facility for quarantine pests'), ('gmo_contained_use', 'Authorisation for contained use of GMOs'), ('pathogen_work_permit', 'Permit to work with pathogens')], max_length=30),
        ),
        migrations.AddConstraint(
            model_name='recipientpermit',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ['sujb_vrat', 'sujb_rat_notice', 'sujb_exception', 'plant_health_loa', 'plant_health_isolation', 'gmo_contained_use', 'pathogen_work_permit'])), name='distribution_permit_kind_valid'),
        ),
    ]
