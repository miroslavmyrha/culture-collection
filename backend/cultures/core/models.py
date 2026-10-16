import uuid

from django.db import models


class PublicModel(models.Model):
    """Internal integer primary key, public UUID for URLs and the API.

    Sequential ids never leave the server, so they cannot be enumerated.

    Index and constraint names are explicit (app_model_field_suffix), so a later
    migration can drop or rename them by a name that is the same on every
    database. A subclass that declares its own Meta must inherit this one
    (`class Meta(PublicModel.Meta)`) or it loses the unique constraint; the
    system check core.E001 catches that.

    Adding PublicModel (or public_id) to an existing table needs three
    migrations, never one: a callable default runs once per migration, so
    every existing row would get the same UUID and the unique constraint fails.
      1. add public_id nullable, without unique
      2. backfill a uuid4 per row in batches (RunPython, reverse noop)
      3. make it non-null and add the named unique constraint
    """

    public_id = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=["public_id"], name="%(app_label)s_%(class)s_public_id_uniq"
            ),
        ]
