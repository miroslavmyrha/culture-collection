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


class LoginFailures(models.Model):
    """Failed logins of one counter in its current window (cultures.users.login_limits).

    Three kinds of row, told apart by which key is empty: (account, address) for
    one account from one address bucket, (account, "") for the account from every
    address, ("", address) for the address bucket across every account. Both keys
    are HMACs, so the table holds no user name and no IP address, only keys,
    times and counts. Rows are written by one upsert per failure and deleted by
    a success (its own pair only), a staff clear and `manage.py prune_login_failures`.
    """

    pk = models.CompositePrimaryKey("account", "address")
    account = models.CharField(max_length=64)
    address = models.CharField(max_length=64)
    window_ends_at = models.DateTimeField()  # the count starts again at 1 after this
    last_failure_at = models.DateTimeField()  # the pair's back-off runs from here
    failures = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(account="", address=""),
                name="users_loginfailures_has_a_key",
            ),
            models.CheckConstraint(
                condition=models.Q(failures__gte=1), name="users_loginfailures_failures_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.failures} failures until {self.window_ends_at:%Y-%m-%d %H:%M}"
