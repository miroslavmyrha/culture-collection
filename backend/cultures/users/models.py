import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user from the first migration: changing it later is very costly."""

    public_id = models.UUIDField(default=uuid.uuid4, editable=False)

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="users_user_public_id_uniq"),
        ]
