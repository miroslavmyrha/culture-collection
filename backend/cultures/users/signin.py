"""The two steps of a sign-in (ADR 0009, #176), kept in the session.

The password step does not sign anyone in: it rotates the session key and stores who passed
it, with that user's session hash and the time (PENDING). Django's login() runs only after a
second factor, or after the first one is enrolled, and marks the session with the time of
that second factor (VERIFIED_AT). SecondFactorMiddleware ends every signed-in session without
the mark, so no other path to login() (an old session from before #176, a view that calls
login() itself) yields a session without a second factor.

A pending step expires after MFA_PENDING_SECONDS, and ends when the user's password, active
flag or session hash changes. Removing a factor, adding one to a signed-in account and new
recovery codes need a second factor of the last MFA_STEP_UP_SECONDS (fresh()).

WebAuthn challenges and the TOTP secret being set up wait in the session too, the secret
sealed with MFA_SECRET_KEY, each with its time.
"""

import base64
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import login, logout
from django.http import HttpRequest, HttpResponseBase
from rest_framework.request import Request

from .factors import KeyRefused, seal, unseal
from .login_limits import Attempt, Surface
from .models import User

PENDING = "cultures.signin.pending"
VERIFIED_AT = "cultures.signin.second_factor_at"
CHALLENGE = "cultures.signin.webauthn_challenge"
TOTP_SETUP = "cultures.signin.totp_setup"
ENROLMENT = "cultures.signin.enrolment_code"
CEREMONY_SECONDS = 5 * 60
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


@dataclass(frozen=True)
class Pending:
    user: User
    username: str  # as typed: the login limits count by it
    surface: Surface


def begin(request: HttpRequest, user: User, username: str, surface: Surface) -> None:
    """The password was right: remember who, in a new session key (no fixation). Whoever was
    signed in in this browser is signed out first: the next person starts from nothing."""
    if isinstance(getattr(request, "user", None), User):
        logout(request)
    request.session.cycle_key()
    request.session[PENDING] = {
        "user": user.pk,
        "hash": user.get_session_auth_hash(),
        "username": username,
        "surface": surface.value,
        "at": time.time(),
    }
    request.session.pop(VERIFIED_AT, None)
    request.session.pop(ENROLMENT, None)


def pending(request: HttpRequest) -> Pending | None:
    """Who passed the password step and has not given the second factor yet, if still valid."""
    data = request.session.get(PENDING)
    if not isinstance(data, dict) or time.time() - data.get("at", 0) > settings.MFA_PENDING_SECONDS:
        return None
    user_id = data.get("user")
    if not isinstance(user_id, int):
        return None
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or user.get_session_auth_hash() != data.get("hash"):
        return None
    return Pending(user, str(data.get("username", "")), Surface(data.get("surface", "api")))


def attempt_for(request: HttpRequest | Request, step: Pending) -> Attempt:
    return Attempt.of(request, step.username, step.surface)


def finish(request: HttpRequest, step: Pending, response: HttpResponseBase) -> None:
    """The second factor was right: sign in (Django rotates the key again) and mark it."""
    login(request, step.user)
    request.session.pop(PENDING, None)
    request.session.pop(ENROLMENT, None)
    mark_verified(request)
    attempt_for(request, step).succeeded(step.user, response)


def mark_verified(request: HttpRequest) -> None:
    request.session[VERIFIED_AT] = time.time()


def is_verified(request: HttpRequest) -> bool:
    return isinstance(request.session.get(VERIFIED_AT), float)


def fresh(request: HttpRequest) -> bool:
    """A second factor within MFA_STEP_UP_SECONDS in this session."""
    at = request.session.get(VERIFIED_AT)
    return isinstance(at, float) and time.time() - at <= settings.MFA_STEP_UP_SECONDS


def allow_enrolment(request: HttpRequest, step: Pending) -> None:
    """The enrolment code was right: this password step may enrol a first factor (#176)."""
    request.session[ENROLMENT] = step.user.pk


def enrolment_allowed(request: HttpRequest, step: Pending) -> bool:
    return request.session.get(ENROLMENT) == step.user.pk


# --- WebAuthn ceremonies ----------------------------------------------------------------------


def site(request: HttpRequest) -> tuple[str, list[str]]:
    """The relying party id and the origins a key operation may come from. From settings in
    production; local and test settings accept the request's own localhost origin."""
    if settings.WEBAUTHN_ORIGINS:
        origins = list(settings.WEBAUTHN_ORIGINS)
        return settings.WEBAUTHN_RP_ID or urlsplit(origins[0]).hostname or "", origins
    if settings.WEBAUTHN_ALLOW_LOCALHOST:
        origin = request.headers.get("Origin") or f"{request.scheme}://{request.get_host()}"
        host = urlsplit(origin).hostname or ""
        if host in LOCAL_HOSTS:
            return host, [origin]
    raise KeyRefused("Security keys are not set up on this server (WEBAUTHN_ORIGINS).")


def keep_challenge(request: HttpRequest, purpose: str, challenge: bytes) -> None:
    request.session[CHALLENGE] = {
        "purpose": purpose,
        "value": base64.b64encode(challenge).decode(),
        "at": time.time(),
    }


def take_challenge(request: HttpRequest, purpose: str) -> bytes | None:
    """The challenge of the ceremony that runs, once: a second answer gets none."""
    data: Any = request.session.pop(CHALLENGE, None)
    if not isinstance(data, dict) or data.get("purpose") != purpose:
        return None
    if time.time() - data.get("at", 0) > CEREMONY_SECONDS:
        return None
    return base64.b64decode(data["value"])


def keep_totp_setup(request: HttpRequest, secret: str) -> None:
    request.session[TOTP_SETUP] = {"secret": seal(secret), "at": time.time()}


def totp_setup(request: HttpRequest) -> str | None:
    data: Any = request.session.get(TOTP_SETUP)
    if not isinstance(data, dict) or time.time() - data.get("at", 0) > settings.MFA_PENDING_SECONDS:
        return None
    return unseal(data["secret"]) or None


def end_totp_setup(request: HttpRequest) -> None:
    request.session.pop(TOTP_SETUP, None)
