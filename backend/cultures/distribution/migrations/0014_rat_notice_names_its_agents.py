"""A notice to SÚJB of handling risky agents states the kind of agent it is for (act 281/2002
Sb., § 17a(3) a)), so it joins the kinds that name what they cover (#173).

A notice recorded before this migration without the agents it names breaks the constraint and
stops the migration: end that permit and record it again from the document, with its agents. No
value is filled in here, because nobody but the document knows what the notice says.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('distribution', '0013_depositor_answer_audit_and_guard'),
        ('labs', '0006_vrataccess_audit_and_guards'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='recipientpermit',
            name='distribution_permit_names_what_it_covers',
        ),
        migrations.AddConstraint(
            model_name='recipientpermit',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind__in', frozenset(['plant_health_loa', 'sujb_exception', 'sujb_rat_notice', 'sujb_vrat'])), _negated=True), ('covers__regex', '\\S'), _connector='OR'), name='distribution_permit_names_what_it_covers'),
        ),
    ]
