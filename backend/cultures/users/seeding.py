"""What seed_dev and seed_e2e make of users, through the services.

Found again by username, so a second run creates nobody twice. A user found is brought back to
what the seed names (active, with the seed's password or none), changed only where it differs.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    ENROLMENT_CODE_ISSUED,
    SECOND_FACTOR_ADDED,
    SECOND_FACTOR_REMOVED,
    EventType,
)
from cultures.labs.models import Lab

from . import services
from .factors import SUBJECT, seal, unseal
from .models import EnrolmentCode, RecoveryCode, SecurityKey, TotpDevice, User


def user(username: str, password: str | None) -> User:
    """An active user with this password (None: no usable one), changed only where needed."""
    found = User.objects.filter(username=username).first()
    if found is None:
        return services.user_create(username=username, password=password)
    if not found.is_active:
        found = services.user_activate(user=found)
    wrong = found.has_usable_password() if password is None else not found.check_password(password)
    if wrong:
        found = services.user_set_password(user=found, raw_password=password)
    return found


def superuser(username: str, password: str) -> None:
    """An active staff superuser with this password. A new one is made through
    User.objects.create_superuser, the project's superuser path (the services, with the audit
    context's reason)."""
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, password=password)
        return
    found = user(username, password)
    services.user_set_staff(user=found, is_staff=True)
    services.user_set_superuser(user=found, is_superuser=True)


def totp(user: User, secret: str) -> None:
    """An authenticator app with this known secret (#176), so the e2e tests and the dev users
    compute their codes. Its last step starts at 0: a code of now is accepted right after the
    seed. Development and CI only: the callers refuse to run without DEBUG."""
    with audited_atomic():  # the row changes carry the command's request id
        device = TotpDevice.objects.filter(user=user).first()
        if device is not None and unseal(device.secret) == secret and not device.last_step:
            return
        if device is not None:
            device.delete()
            _factor_event(SECOND_FACTOR_REMOVED, user, {"totp": ["added", None]})
        TotpDevice.objects.create(user=user, secret=seal(secret))
        # The same event as factors.totp_enrol: every row change has its event (audit_reconcile).
        _factor_event(SECOND_FACTOR_ADDED, user, {"totp": [None, "added"]})


def _factor_event(event: EventType, user: User, change: dict[str, list[object]]) -> None:
    record_event(event, Change(SUBJECT, user.public_id, change))


def no_factor(user: User) -> None:
    """No key, no authenticator app, no recovery code: the next sign-in enrols one (#176)."""
    with audited_atomic():
        for key in SecurityKey.objects.filter(user=user):
            public_id = str(key.public_id)
            key.delete()
            _factor_event(SECOND_FACTOR_REMOVED, user, {"security_key": [public_id, None]})
        if TotpDevice.objects.filter(user=user).delete()[0]:
            _factor_event(SECOND_FACTOR_REMOVED, user, {"totp": ["added", None]})
        if RecoveryCode.objects.filter(user=user).delete()[0]:
            _factor_event(SECOND_FACTOR_REMOVED, user, {"recovery_codes": ["issued", None]})


def enrolment_code(user: User, *, issued_by: User, lab: Lab | None, code: str) -> None:
    """An enrolment code with this known value (#176), unused and valid from now, so the e2e
    test of a first enrolment types it. Development and CI only, as totp() above."""
    folded = code.strip().lower().replace("-", "")
    with audited_atomic():
        now = timezone.now()
        valid = EnrolmentCode.objects.filter(user=user, used_at__isnull=True, expires_at__gt=now)
        if any(check_password(folded, c.code_hash) for c in valid):
            return  # a second run changes nothing
        reason = "e2e: the first enrolment of a security key"
        entry = EnrolmentCode.objects.create(
            user=user,
            lab=lab,
            issued_by=issued_by,
            reason=reason,
            code_hash=make_password(folded),
            created_at=now,
            expires_at=now + timedelta(hours=settings.ENROLMENT_CODE_HOURS),
        )
        # As factors.enrolment_code_issue records it, with its reason.
        record_event(
            ENROLMENT_CODE_ISSUED,
            Change(
                SUBJECT,
                user.public_id,
                {"enrolment_code": [None, entry.pk]},
                lab_id=lab.pk if lab else None,
            ),
            reason=reason,
        )
