"""The second factor (ADR 0009, #176): WebAuthn security keys first, TOTP as the fallback, and
single-use recovery codes.

Every write runs in audited_atomic() and records one event, which names the kind of factor
and its public id, never a secret, a code or key material. The TOTP secret is stored encrypted
with MFA_SECRET_KEY (Fernet), the recovery codes hashed with the password hasher.

A user always keeps one factor (a key or the TOTP device): removing the last one is refused.
Losing every factor and every recovery code takes a reset by two people (FactorReset): a
manager of a lab the user belongs to proposes, another manager of that lab confirms (two
superusers for a user in no lab), neither of them the user. The confirmation removes every
factor and ends the user's sessions, and the user enrols again at the next sign-in. The
database holds the same rules (users 0008 and 0009).

Lock order as everywhere: the user row first, then the lab, then the rows of that lab.
"""

import base64
import hashlib
import json
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, parse_authentication_credential_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    ENROLMENT_CODE_ISSUED,
    ENROLMENT_CODE_USED,
    FACTOR_RESET_CONFIRMED,
    FACTOR_RESET_PROPOSED,
    FACTOR_RESET_WITHDRAWN,
    RECOVERY_CODE_USED,
    RECOVERY_CODES_ISSUED,
    SECOND_FACTOR_ADDED,
    SECOND_FACTOR_REMOVED,
)
from cultures.core.constraints import save_arbitrated
from cultures.core.exceptions import Conflict, Forbidden, NotFound, RuleViolation
from cultures.labs.locks import lock_lab
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role

from .models import (
    FACTOR_RESET_OPEN_UNIQUE,
    EnrolmentCode,
    FactorReset,
    RecoveryCode,
    SecurityKey,
    TotpDevice,
    User,
)
from .sessions import end_sessions

SUBJECT = "user"
TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_WINDOW = 1  # one step either way: clocks drift
RECOVERY_CODES = 10
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i to misread
RECOVERY_LENGTH = 10
KEY_NAME_MAX = 60


class WrongCode(RuleViolation):
    default_code = "wrong_code"
    default_detail = "The code is not valid. Enter the current code, or a recovery code."


class KeyRefused(RuleViolation):
    default_code = "key_refused"
    default_detail = "The security key was not accepted. Try again, or use another factor."


class TotpExists(Conflict):
    default_code = "totp_exists"
    default_detail = "This account has an authenticator app already. Remove it first."


class LastFactor(RuleViolation):
    default_code = "last_factor"
    default_detail = "The last second factor stays. Add another one before removing this one."


class ResetExists(Conflict):
    default_code = "reset_exists"
    default_detail = "A reset of this person's second factor waits for confirmation already."


class ResetClosed(Conflict):
    default_code = "reset_closed"
    default_detail = "This reset was confirmed or withdrawn already."


class ConfirmOwnReset(RuleViolation):
    default_code = "confirm_own_reset"
    default_detail = "Another person confirms a reset you proposed, or one of your own."


class ResetOwnFactor(RuleViolation):
    default_code = "reset_own_factor"
    default_detail = (
        "Nobody resets their own second factor or issues their own enrolment code."
        " Ask another manager of your lab."
    )


# --- reading ---------------------------------------------------------------------------------


def has_second_factor(user: User) -> bool:
    return (
        SecurityKey.objects.filter(user=user).exists()
        or TotpDevice.objects.filter(user=user).exists()
    )


def factor_count(user: User) -> int:
    return SecurityKey.objects.filter(user=user).count() + int(
        TotpDevice.objects.filter(user=user).exists()
    )


def unused_recovery_codes(user: User) -> int:
    return RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


def methods(user: User) -> list[str]:
    """The ways this user can give a second factor now, in the order the sign-in offers them."""
    found = []
    if SecurityKey.objects.filter(user=user).exists():
        found.append("security_key")
    if TotpDevice.objects.filter(user=user).exists():
        found.append("totp")
    if unused_recovery_codes(user):
        found.append("recovery_code")
    return found


# --- TOTP -------------------------------------------------------------------------------------


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.MFA_SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def unseal(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        # Another MFA_SECRET_KEY: the device cannot be read, the user takes another factor.
        return ""


def totp_new_secret() -> str:
    return pyotp.random_base32()


def totp_uri(user: User, secret: str) -> str:
    return pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_PERIOD).provisioning_uri(
        name=user.username, issuer_name=settings.WEBAUTHN_RP_NAME
    )


def _matching_step(secret: str, code: str, now: float) -> int | None:
    """The time step whose code this is, within the window, or None."""
    if not secret or len(code) != TOTP_DIGITS or not (code.isascii() and code.isdigit()):
        return None
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_PERIOD)
    current = int(now // TOTP_PERIOD)
    for step in range(current - TOTP_WINDOW, current + TOTP_WINDOW + 1):
        if secrets.compare_digest(totp.at(step * TOTP_PERIOD), code):
            return step
    return None


def totp_enrol(*, user: User, secret: str, code: str) -> TotpDevice:
    """The authenticator app, after the user typed its current code (so the secret arrived)."""
    step = _matching_step(secret, code.strip(), time.time())
    if step is None:
        raise WrongCode(attr="code")
    with audited_atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if TotpDevice.objects.filter(user=locked).exists():
            raise TotpExists
        device = TotpDevice.objects.create(user=locked, secret=seal(secret), last_step=step)
        record_event(
            SECOND_FACTOR_ADDED, Change(SUBJECT, locked.public_id, {"totp": [None, "added"]})
        )
    return device


def totp_verify(*, user: User, code: str) -> bool:
    """A code of the current window, never one taken before (each step is used once)."""
    with audited_atomic():
        device = TotpDevice.objects.select_for_update().filter(user=user).first()
        if device is None:
            return False
        step = _matching_step(unseal(device.secret), code.strip(), time.time())
        if step is None or step <= device.last_step:
            return False
        device.last_step, device.last_used_at = step, timezone.now()
        device.save(update_fields=["last_step", "last_used_at"])
    return True


# --- security keys (WebAuthn) ---------------------------------------------------------------


@dataclass(frozen=True)
class Ceremony:
    """The options for the browser, and the challenge the server keeps until the answer."""

    options: dict[str, Any]
    challenge: bytes


def _descriptors(user: User) -> list[PublicKeyCredentialDescriptor]:
    keys = SecurityKey.objects.filter(user=user).values_list("credential_id", "transports")
    return [
        PublicKeyCredentialDescriptor(
            id=bytes(credential), transports=[AuthenticatorTransport(t) for t in transports]
        )
        for credential, transports in keys
    ]


def _as_dict(options: Any) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(options_to_json(options))
    return result


def key_registration(user: User, rp_id: str) -> Ceremony:
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_name=user.username,
        user_id=user.public_id.bytes,
        exclude_credentials=_descriptors(user),
        # Preferred, not required (Mirek, 2026-11-22): a hardware key without a PIN or a
        # fingerprint is still something the person holds, next to the password, which is the
        # second factor ADR 0009 asks for. Required would refuse those keys outright.
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    return Ceremony(_as_dict(options), options.challenge)


def key_enrol(
    *,
    user: User,
    credential: dict[str, Any],
    challenge: bytes,
    rp_id: str,
    origins: Sequence[str],
    name: str,
) -> SecurityKey:
    """A new key, from the browser's answer to key_registration's challenge."""
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=list(origins),
        )
    except WebAuthnException as exc:
        raise KeyRefused from exc
    transports = [str(t) for t in credential.get("response", {}).get("transports", [])][:8]
    with audited_atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        key = SecurityKey(
            user=locked,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=[t for t in transports if t in {a.value for a in AuthenticatorTransport}],
            name=(name.strip() or "Security key")[:KEY_NAME_MAX],
        )
        save_arbitrated(key, {"users_securitykey_credential_id_uniq": KeyRefused()})
        record_event(
            SECOND_FACTOR_ADDED,
            Change(SUBJECT, locked.public_id, {"security_key": [None, str(key.public_id)]}),
        )
    return key


def key_authentication(user: User, rp_id: str) -> Ceremony:
    options = generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=_descriptors(user),
        user_verification=UserVerificationRequirement.PREFERRED,  # see key_registration
    )
    return Ceremony(_as_dict(options), options.challenge)


def key_verify(
    *, user: User, credential: dict[str, Any], challenge: bytes, rp_id: str, origins: Sequence[str]
) -> bool:
    """The answer to key_authentication's challenge, by one of the user's own keys. A sign
    count that does not grow (a cloned key) is refused by py_webauthn."""
    try:
        raw_id = base64url_to_bytes(parse_authentication_credential_json(credential).id)
    except (WebAuthnException, ValueError):
        return False
    with audited_atomic():
        key = (
            SecurityKey.objects.select_for_update().filter(user=user, credential_id=raw_id).first()
        )
        if key is None:
            return False
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=rp_id,
                expected_origin=list(origins),
                credential_public_key=bytes(key.public_key),
                credential_current_sign_count=key.sign_count,
            )
        except WebAuthnException:
            return False
        key.sign_count, key.last_used_at = verified.new_sign_count, timezone.now()
        key.save(update_fields=["sign_count", "last_used_at", "updated_at"])
    return True


# --- recovery codes ---------------------------------------------------------------------------


def _new_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def _fold(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def recovery_codes_issue(*, user: User) -> list[str]:
    """Ten new codes in place of the old ones. The plain codes leave here once, never stored."""
    codes = [_new_code() for _ in range(RECOVERY_CODES)]
    with audited_atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        RecoveryCode.objects.filter(user=locked).delete()
        RecoveryCode.objects.bulk_create(
            RecoveryCode(user=locked, code_hash=make_password(_fold(code))) for code in codes
        )
        record_event(
            RECOVERY_CODES_ISSUED,
            Change(SUBJECT, locked.public_id, {"recovery_codes": [None, RECOVERY_CODES]}),
        )
    return codes


def recovery_code_use(*, user: User, code: str) -> bool:
    """An unused code of this user, then never again."""
    folded = _fold(code)
    if not folded:
        return False
    with audited_atomic():
        unused = RecoveryCode.objects.select_for_update().filter(user=user, used_at__isnull=True)
        match = next((c for c in unused if check_password(folded, c.code_hash)), None)
        if match is None:
            return False
        match.used_at = timezone.now()
        match.save(update_fields=["used_at"])
        left = unused_recovery_codes(user)
        record_event(
            RECOVERY_CODE_USED,
            Change(SUBJECT, user.public_id, {"recovery_codes": [left + 1, left]}),
        )
    return True


# --- removal ----------------------------------------------------------------------------------


def key_remove(*, user: User, key: SecurityKey) -> None:
    """One of the user's own keys. The caller checked a fresh second factor."""
    with audited_atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        found = SecurityKey.objects.filter(pk=key.pk, user=locked).first()
        if found is None:
            raise NotFound
        if factor_count(locked) <= 1:
            raise LastFactor
        public_id = str(found.public_id)
        found.delete()
        record_event(
            SECOND_FACTOR_REMOVED,
            Change(SUBJECT, locked.public_id, {"security_key": [public_id, None]}),
        )


def totp_remove(*, user: User) -> None:
    """The user's authenticator app. The caller checked a fresh second factor."""
    with audited_atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        device = TotpDevice.objects.filter(user=locked).first()
        if device is None:
            raise NotFound
        if factor_count(locked) <= 1:
            raise LastFactor
        device.delete()
        record_event(
            SECOND_FACTOR_REMOVED, Change(SUBJECT, locked.public_id, {"totp": ["added", None]})
        )


def remove_all(user: User) -> tuple[int, int, int]:
    """Every key, the TOTP device and every recovery code of the user: (keys, devices, codes).
    For a confirmed reset and for an erasure; the caller holds the user's lock and records."""
    keys = SecurityKey.objects.filter(user=user).delete()[0]
    devices = TotpDevice.objects.filter(user=user).delete()[0]
    codes = RecoveryCode.objects.filter(user=user).delete()[0]
    return keys, devices, codes


# --- the enrolment code -------------------------------------------------------------------------


def enrolment_code_issue(*, actor: User, user: User, lab: Lab | None, reason: str) -> str:
    """A one-time code for the first enrolment of a factor, from a manager of a lab the user
    belongs to (a superuser when no lab is named), with a reason. The plain code leaves here
    once, to be handed over; only its hash is stored."""
    reason = _reason(reason)
    code = _new_code()
    with audited_atomic():
        locked = _locked_decision(actor, user, lab)
        _issue(actor, locked, lab, reason, code)
    return code


def _issue(actor: User, user: User, lab: Lab | None, reason: str, code: str) -> None:
    """Caller holds the locks of _locked_decision."""
    now = timezone.now()
    entry = EnrolmentCode.objects.create(
        user=user,
        lab=lab,
        issued_by=actor,
        reason=reason,
        code_hash=make_password(_fold(code)),
        created_at=now,
        expires_at=now + timedelta(hours=settings.ENROLMENT_CODE_HOURS),
    )
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


def enrolment_code_use(*, user: User, code: str) -> bool:
    """An unused code of this user that has not expired, then never again."""
    folded = _fold(code)
    if not folded:
        return False
    with audited_atomic():
        now = timezone.now()
        valid = EnrolmentCode.objects.select_for_update().filter(
            user=user, used_at__isnull=True, expires_at__gt=now
        )
        match = next((c for c in valid if check_password(folded, c.code_hash)), None)
        if match is None:
            return False
        match.used_at = now
        match.save(update_fields=["used_at"])
        record_event(
            ENROLMENT_CODE_USED,
            Change(SUBJECT, user.public_id, {"enrolment_code": [match.pk, None]}),
        )
    return True


# --- the reset by two people ------------------------------------------------------------------


def _may_decide(actor: User, user: User, lab: Lab | None) -> bool:
    """A manager of the lab who is not the user, for a user of that lab; a superuser when the
    reset names no lab. Read under the locks of the caller."""
    if actor.pk == user.pk or not actor.is_active:
        return False
    if lab is None:
        return actor.is_superuser
    members = Membership.objects.filter(lab=lab)
    return (
        members.filter(user=actor, role=Role.MANAGER).exists()
        and members.filter(user=user).exists()
    )


def _locked_decision(actor: User, user: User, lab: Lab | None) -> User:
    """The user's row, then the lab, locked; the actor's right to decide, as committed now."""
    locked = User.objects.select_for_update().get(pk=user.pk)
    if lab is not None:
        lock_lab(lab.pk)
    fresh_actor = User.objects.get(pk=actor.pk)
    if fresh_actor.pk == locked.pk:
        raise ResetOwnFactor
    if not _may_decide(fresh_actor, locked, lab):
        raise Forbidden
    return locked


def _reason(reason: str) -> str:
    text = reason.strip()
    if not text:
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return text


def _change(reset: FactorReset, changes: dict[str, Any]) -> Change:
    return Change(SUBJECT, reset.user.public_id, changes, lab_id=reset.lab_id)


def factor_reset_propose(*, actor: User, user: User, lab: Lab | None, reason: str) -> FactorReset:
    reason = _reason(reason)
    with audited_atomic():
        locked = _locked_decision(actor, user, lab)
        reset = FactorReset(user=locked, lab=lab, proposed_by=actor, reason=reason)
        save_arbitrated(reset, {FACTOR_RESET_OPEN_UNIQUE: ResetExists()})
        record_event(
            FACTOR_RESET_PROPOSED,
            _change(reset, {"factor_reset": [None, str(reset.public_id)]}),
            reason=reason,
        )
    return reset


def _locked_open_reset(actor: User, reset: FactorReset) -> FactorReset:
    _locked_decision(actor, reset.user, reset.lab)
    locked = FactorReset.objects.select_for_update().select_related("user").get(pk=reset.pk)
    if locked.confirmed_at is not None or locked.withdrawn_at is not None:
        raise ResetClosed
    return locked


def factor_reset_confirm(
    *, actor: User, reset: FactorReset, reason: str
) -> tuple[FactorReset, str]:
    """Another decider than the proposer takes every factor of the user away, and gets an
    enrolment code to hand over with it: the one who just checked who is asking hands it over
    at once, so the person is never left with no way in and no third step waits."""
    reason = _reason(reason)
    with audited_atomic():
        locked = _locked_open_reset(actor, reset)
        if actor.pk in {locked.proposed_by_id, locked.user_id}:
            raise ConfirmOwnReset
        user = locked.user
        keys, devices, codes = remove_all(user)
        sessions = end_sessions(user)
        locked.confirmed_by, locked.confirmed_at, locked.confirm_reason = (
            actor,
            timezone.now(),
            reason,
        )
        locked.save(update_fields=["confirmed_by", "confirmed_at", "confirm_reason", "updated_at"])
        record_event(
            FACTOR_RESET_CONFIRMED,
            _change(
                locked,
                {
                    "factor_reset": [None, str(locked.public_id)],
                    "security_keys": [keys, 0],
                    "totp": [devices, 0],
                    "recovery_codes": [codes, 0],
                    "sessions": [sessions, 0],
                },
            ),
            reason=reason,
        )
        code = _new_code()
        _issue(actor, user, locked.lab, reason, code)
    return locked, code


def factor_reset_withdraw(*, actor: User, reset: FactorReset, reason: str) -> FactorReset:
    reason = _reason(reason)
    with audited_atomic():
        locked = _locked_open_reset(actor, reset)
        locked.withdrawn_by, locked.withdrawn_at, locked.withdraw_reason = (
            actor,
            timezone.now(),
            reason,
        )
        locked.save(update_fields=["withdrawn_by", "withdrawn_at", "withdraw_reason", "updated_at"])
        record_event(
            FACTOR_RESET_WITHDRAWN,
            _change(locked, {"factor_reset": [str(locked.public_id), None]}),
            reason=reason,
        )
    return locked
