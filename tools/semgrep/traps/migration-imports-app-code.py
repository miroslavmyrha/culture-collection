import uuid

# ok: migration-imports-app-code
from django.db import migrations, models

# ruleid: migration-imports-app-code
from lab.models import Sample

# ruleid: migration-imports-app-code
from lab.choices import Status

# ok: migration-imports-app-code
from lab.fields import BarcodeField

# ok: migration-imports-app-code
from lab.models import SampleManager

# ok: migration-imports-app-code
from lab.migrations.tools.models import SafeDeleteModel


def backfill(apps, schema_editor):
    model = apps.get_model("lab", "Sample")
    model.objects.filter(public_id=None).update(public_id=uuid.uuid4())
