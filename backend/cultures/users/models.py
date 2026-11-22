import uuid
from typing import Any, ClassVar

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models

from cultures.core.models import PublicModel
from cultures.labs.querysets import LabScopedQuerySet


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


# The username of an erased user: this prefix and the public id (services.user_erase).
ERASED_PREFIX = "erased-"


class User(AbstractUser):
    """Custom user from the first migration: changing it later is very costly.

    An erased user (erased_at set, #37) is a tombstone: the row stays so that
    every audit row and admin log entry still points at it, with id, public_id
    and date_joined kept and every personal value gone. The check constraint
    holds that for every writer, not only the service.
    """

    public_id = models.UUIDField(default=uuid.uuid4, editable=False)
    erased_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects: ClassVar[UserManager] = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(fields=["public_id"], name="users_user_public_id_uniq"),
            models.CheckConstraint(
                condition=models.Q(erased_at__isnull=True)
                | models.Q(
                    first_name="",
                    last_name="",
                    email="",
                    is_active=False,
                    is_staff=False,
                    is_superuser=False,
                    username__startswith=ERASED_PREFIX,
                ),
                name="users_user_erased_is_a_tombstone",
            ),
        ]

    @property
    def is_erased(self) -> bool:
        return self.erased_at is not None


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


# The second factor (ADR 0009, #176): WebAuthn keys first, TOTP as the fallback, recovery codes.
# cultures.users.factors writes these rows. Django's login() runs only after a second factor,
# so an account without one reaches only the enrolment steps.


class SecurityKey(PublicModel):
    """A WebAuthn credential (a hardware key or a passkey). A user may hold several."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="security_keys")
    credential_id = models.BinaryField()
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    name = models.CharField(max_length=60)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["credential_id"], name="users_securitykey_credential_id_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(sign_count__gte=0), name="users_securitykey_sign_count_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(name__regex=r"\S"), name="users_securitykey_name_given"
            ),
        ]


class TotpDevice(models.Model):
    """The TOTP secret of a user (RFC 6238, 30 s, 6 digits), encrypted with MFA_SECRET_KEY.

    last_step is the last time step a code was accepted for: a code is never taken twice.
    """

    user = models.OneToOneField(User, on_delete=models.PROTECT, related_name="totp_device")
    secret = models.TextField()  # Fernet token, never the plain secret
    created_at = models.DateTimeField(auto_now_add=True)
    last_step = models.BigIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return "Authenticator app"


class RecoveryCode(models.Model):
    """A single-use recovery code, hashed with the password hasher. Shown once when issued."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="recovery_codes")
    code_hash = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return "Recovery code, used" if self.used_at else "Recovery code"


FACTOR_RESET_OPEN_UNIQUE = "users_factorreset_open_uniq"


class FactorReset(PublicModel):
    """Two people take away every second factor of a user who lost them all (#176).

    A manager of a lab the user belongs to proposes, another manager of that lab confirms; for a
    user in no lab (staff), two superusers. Neither is the user. The confirmation removes the
    keys, the TOTP device and the recovery codes, and the user enrols again at the next sign-in.
    Withdrawn or confirmed once, never changed after that (the trigger of users 0010).
    """

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="factor_resets")
    lab = models.ForeignKey(
        "labs.Lab", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    proposed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    confirmed_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirm_reason = models.TextField(blank=True)
    withdrawn_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdraw_reason = models.TextField(blank=True)

    # The resets of a lab are read by its managers; a reset without a lab (staff) by nobody's
    # lab role, only by superusers through the service.
    objects = LabScopedQuerySet["FactorReset"].as_manager()

    class Meta(PublicModel.Meta):
        constraints = [
            *PublicModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(confirmed_at__isnull=True, withdrawn_at__isnull=True),
                name=FACTOR_RESET_OPEN_UNIQUE,
            ),
            models.CheckConstraint(
                condition=models.Q(reason__regex=r"\S"), name="users_factorreset_reason_given"
            ),
            models.CheckConstraint(
                condition=~models.Q(proposed_by=models.F("user")),
                name="users_factorreset_not_by_the_user",
            ),
            # isnull=False spelled out: a CHECK passes when its condition is NULL.
            models.CheckConstraint(
                condition=models.Q(
                    confirmed_at__isnull=True, confirmed_by__isnull=True, confirm_reason=""
                )
                | models.Q(
                    confirmed_at__isnull=False,
                    confirmed_by__isnull=False,
                    confirm_reason__regex=r"\S",
                ),
                name="users_factorreset_confirmation_complete",
            ),
            models.CheckConstraint(
                condition=models.Q(confirmed_by__isnull=True)
                | (
                    ~models.Q(confirmed_by=models.F("proposed_by"))
                    & ~models.Q(confirmed_by=models.F("user"))
                ),
                name="users_factorreset_confirmed_by_another",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    withdrawn_at__isnull=True, withdrawn_by__isnull=True, withdraw_reason=""
                )
                | models.Q(
                    withdrawn_at__isnull=False,
                    withdrawn_by__isnull=False,
                    withdraw_reason__regex=r"\S",
                ),
                name="users_factorreset_withdrawal_complete",
            ),
            models.CheckConstraint(
                condition=models.Q(confirmed_at__isnull=True) | models.Q(withdrawn_at__isnull=True),
                name="users_factorreset_confirmed_or_withdrawn",
            ),
        ]


class EnrolmentCode(models.Model):
    """A one-time code from a manager that lets an account without a second factor enrol its
    first one (#176): the password alone never gets in. A manager of a lab the user belongs to
    issues it with a reason (a superuser for a user in no lab), it is valid for
    ENROLMENT_CODE_HOURS, hashed with the password hasher, shown once, and used once (the
    trigger of users 0011 also refuses a use after it expired)."""

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="enrolment_codes")
    lab = models.ForeignKey(
        "labs.Lab", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    code_hash = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    objects = LabScopedQuerySet["EnrolmentCode"].as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reason__regex=r"\S"), name="users_enrolmentcode_reason_given"
            ),
            models.CheckConstraint(
                condition=~models.Q(issued_by=models.F("user")),
                name="users_enrolmentcode_not_by_the_user",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="users_enrolmentcode_expires_later",
            ),
        ]

    def __str__(self) -> str:
        return "Enrolment code, used" if self.used_at else "Enrolment code"
