import uuid
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager["User"]):
    def create_superuser(
        self,
        username: str,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: Any,
    ) -> "User":
        """Through the audited services, so it needs an audit context with a reason.

        Granting superuser status is a privilege change. manage.py
        createsuperuser (cultures.users.management.commands) enters the context;
        anywhere else a missing context raises instead of creating an
        unrecorded superuser. create_user stays Django's plain factory: the row
        trigger records it, and new users in the app come from user_create.
        """
        from .services import superuser_create  # noqa: PLC0415 (services import this module)

        flags = {"is_staff": True, "is_superuser": True}
        unexpected = {k: v for k, v in extra_fields.items() if flags.get(k) is not v}
        if unexpected:
            raise ValueError(f"create_superuser takes no other fields: {sorted(unexpected)}")
        return superuser_create(username=username, password=password, email=email or "")


class User(AbstractUser):
    """Custom user from the first migration: changing it later is very costly."""

    public_id = models.UUIDField(default=uuid.uuid4, editable=False)

    objects: ClassVar[UserManager] = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="users_user_public_id_uniq"),
        ]
