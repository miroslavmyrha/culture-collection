import uuid

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    operations = [
        # ruleid: migration-callable-default
        migrations.AddField(
            model_name="sample",
            name="public_id",
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
        # ruleid: migration-callable-default
        migrations.AddField(
            model_name="sample",
            name="received_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        # ok: migration-callable-default
        migrations.AddField(
            model_name="sample",
            name="public_id_tmp",
            field=models.UUIDField(null=True),
        ),
        # ok: migration-callable-default
        migrations.CreateModel(
            name="Box",
            fields=[("public_id", models.UUIDField(default=uuid.uuid4, unique=True))],
        ),
    ]
