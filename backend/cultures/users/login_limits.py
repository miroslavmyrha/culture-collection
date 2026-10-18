"""Failed-login limits that never lock an account for everyone.

Every login entry point (the API login and the admin login) runs one attempt
through here, after the per-address request throttle (LoginThrottle):

    attempt = Attempt.of(request, username, Surface.API)
    refusal = attempt.refusal()        # a 429 with refusal.wait, or None
    ... check the password ...
    attempt.failed()                   # or: attempt.succeeded(user, response)

Failures are counted in three counters (users_loginfailures, one upsert per
failure, so parallel failures are never lost):
- the pair (account, address bucket): after LOGIN_PAIR_MAX_FAILURES in its
  window the pair waits LOGIN_PAIR_BACKOFF_SECONDS, doubled with each further
  failure. Another address, the real user's, is not affected.
- the address bucket across accounts: LOGIN_ADDRESS_MAX_FAILURES, then the
  address waits for the end of its window. One address guessing many names.
- the account across addresses: LOGIN_ACCOUNT_MAX_FAILURES put the account
  "under attack" until the window ends. Guesses spread over many addresses.

Under attack, only a browser with a valid known-device cookie for that account
may still try (and stays under the pair back-off): the real user signs in from
a browser used before, the botnet does not. The cookie also exempts its holder
from the address budget, so failures of others behind the same address (a lab
behind one NAT) do not lock the real user out. The cookie is set on every
successful login. Each entry is signed with a salt that holds the user's
public id and password hash, so a password change revokes every entry, and
an entry for bob is no proof for alice. It holds no user name.

A success deletes its own pair counter only. Clearing the address or the
account counter would let an attacker with one valid account reset its budget
by signing in between guesses (allauth's ratelimit comment, account/adapter.py).
Staff clear an account's counters with services.user_login_limits_clear.

Names are folded (NFKC, case, surrounding blanks) and the counter keys are
HMACs with their own purpose salt, so neither the table nor the logs hold a
user name. Unknown names are counted and refused exactly like real ones, so
the answer never says whether an account exists. Every failure and refusal
writes one `login_failed` log line with account_ref (16 hex characters of the
account key), ip_bucket, surface, outcome and request_id, never the typed name:
people type their password into it. When an existing account goes under
attack, an AuditEvent login_account_under_attack records it (system actor).

Limit: a stolen known-device cookie takes the account limit away for its
holder. It is HttpOnly and dies with a password change.
"""

import enum
import logging
import math
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.conf import settings
from django.core import signing
from django.db import connection
from django.db.models import Q
from django.http import HttpRequest, HttpResponseBase
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.request import Request

from cultures.audit.context import audit_context, audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.models import ActorKind, Channel
from cultures.audit.registry import LOGIN_ACCOUNT_UNDER_ATTACK
from cultures.core.client_ip import client_bucket
from cultures.core.request_id import current_request_id

from .models import LoginFailures, User

logger = logging.getLogger("cultures.login")

KEY_SALT = "cultures.users.login_limits"  # salted_hmac's purpose: no other HMAC shares the key
DEVICE_SALT = "cultures.users.known_device"
DEVICE_SEPARATOR = "|"  # a legal cookie character that signing never produces
DEVICE_VALUE = "1"
KNOWN_DEVICES_PER_BROWSER = 5  # accounts one browser remembers (a shared lab computer)
ACCOUNT_REF_LENGTH = 16
SYSTEM_LABEL = "login-limits"


class Surface(enum.StrEnum):
    API = "api"
    ADMIN = "admin"


class Outcome(enum.StrEnum):
    BAD_CREDENTIALS = "bad_credentials"
    PAIR_LIMITED = "pair_limited"
    IP_LIMITED = "ip_limited"
    ACCOUNT_UNDER_ATTACK = "account_under_attack"


CHANNELS = {Surface.API: Channel.API, Surface.ADMIN: Channel.WEB}


def normalize_username(username: str) -> str:
    return unicodedata.normalize("NFKC", username).strip().casefold()


def _key(kind: str, value: str) -> str:
    return salted_hmac(KEY_SALT, f"{kind}:{value}", algorithm="sha256").hexdigest()


def account_key(username: str) -> str:
    return _key("account", normalize_username(username))


def address_key(bucket: str) -> str:
    return _key("address", bucket)


def accounts_named(username: str) -> list[User]:
    """The users whose name folds to the same account as `username` (usually one)."""
    folded = normalize_username(username)
    if not folded:
        return []
    return [
        user
        for user in User.objects.filter(username__iexact=folded)
        if normalize_username(user.username) == folded
    ]


def _backoff(failures: int) -> timedelta:
    """The pair's wait after its latest failure: doubles from PAIR_MAX, at most the window."""
    doublings = min(failures - settings.LOGIN_PAIR_MAX_FAILURES, 16)
    seconds = min(
        settings.LOGIN_PAIR_BACKOFF_SECONDS * 2**doublings, settings.LOGIN_PAIR_WINDOW_SECONDS
    )
    return timedelta(seconds=seconds)


@dataclass(frozen=True)
class Refusal:
    outcome: Outcome
    until: datetime

    def wait_seconds(self, now: datetime) -> int:
        """For Retry-After: whole seconds, at least 1."""
        return max(1, math.ceil((self.until - now).total_seconds()))


_UPSERT = """
INSERT INTO users_loginfailures AS f (account, address, window_ends_at, last_failure_at, failures)
VALUES (%s, %s, %s, %s, 1), (%s, %s, %s, %s, 1), (%s, %s, %s, %s, 1)
ON CONFLICT (account, address) DO UPDATE SET
    failures = CASE WHEN f.window_ends_at <= EXCLUDED.last_failure_at
                    THEN 1 ELSE f.failures + 1 END,
    window_ends_at = CASE WHEN f.window_ends_at <= EXCLUDED.last_failure_at
                          THEN EXCLUDED.window_ends_at ELSE f.window_ends_at END,
    last_failure_at = EXCLUDED.last_failure_at
RETURNING account, address, failures
"""


def count_failure(account: str, address: str, now: datetime) -> dict[str, int]:
    """One failure on the pair, the account and the address, atomically per row.

    Returns the new counts by kind ("pair", "account", "address"). The window
    of a row restarts when the failure comes after its end. `now` comes from
    Python, so tests can move the clock. The statement locks its rows in the
    order of VALUES, always pair, account, address, and runs in autocommit, so
    two failures cannot wait on each other's rows in a cycle.
    """
    windows = {
        (account, address): settings.LOGIN_PAIR_WINDOW_SECONDS,
        (account, ""): settings.LOGIN_ACCOUNT_WINDOW_SECONDS,
        ("", address): settings.LOGIN_ADDRESS_WINDOW_SECONDS,
    }
    params: list[str | datetime] = []
    for (row_account, row_address), seconds in windows.items():
        params += [row_account, row_address, now + timedelta(seconds=seconds), now]
    with connection.cursor() as cursor:
        cursor.execute(_UPSERT, params)
        rows = cursor.fetchall()
    kinds = {(account, address): "pair", (account, ""): "account", ("", address): "address"}
    return {kinds[(row_account, row_address)]: count for row_account, row_address, count in rows}


@dataclass
class Attempt:
    """One login attempt: who it names (as a key only) and where it comes from."""

    request: HttpRequest | Request
    username: str
    surface: Surface
    account: str
    address: str
    ip_bucket: str
    _named: list[User] | None = field(default=None, repr=False)
    _known: bool | None = field(default=None, repr=False)

    @classmethod
    def of(cls, request: HttpRequest | Request, username: str, surface: Surface) -> "Attempt":
        bucket = client_bucket(request)
        return cls(
            request=request,
            username=username,
            surface=surface,
            account=account_key(username),
            address=address_key(bucket),
            ip_bucket=bucket,
        )

    @property
    def account_ref(self) -> str:
        return self.account[:ACCOUNT_REF_LENGTH]

    def named_users(self) -> list[User]:
        if self._named is None:
            self._named = accounts_named(self.username)
        return self._named

    def from_known_device(self) -> bool:
        """The browser holds a valid known-device entry for this account."""
        if self._known is None:
            tokens = _device_tokens(self.request)
            self._known = bool(tokens) and any(
                _signed_for(token, user) for token in tokens for user in self.named_users()
            )
        return self._known

    def refusal(self) -> Refusal | None:
        """Whether the counters refuse this attempt before its password is checked."""
        now = timezone.now()
        counters = {
            (row.account, row.address): row
            for row in LoginFailures.objects.filter(
                Q(account=self.account, address=self.address)
                | Q(account=self.account, address="")
                | Q(account="", address=self.address),
                window_ends_at__gt=now,
            )
        }
        refusal = self._gate(counters, now)
        if refusal is not None:
            self._log(refusal.outcome)
        return refusal

    def _gate(
        self, counters: dict[tuple[str, str], LoginFailures], now: datetime
    ) -> Refusal | None:
        # A known device passes both of these: they count other people's failures.
        address_row = counters.get(("", self.address))
        if (
            address_row is not None
            and address_row.failures >= settings.LOGIN_ADDRESS_MAX_FAILURES
            and not self.from_known_device()
        ):
            return Refusal(Outcome.IP_LIMITED, address_row.window_ends_at)
        account_row = counters.get((self.account, ""))
        if (
            account_row is not None
            and account_row.failures >= settings.LOGIN_ACCOUNT_MAX_FAILURES
            and not self.from_known_device()
        ):
            return Refusal(Outcome.ACCOUNT_UNDER_ATTACK, account_row.window_ends_at)
        # The pair counts this browser's own failures: a known device waits too.
        pair = counters.get((self.account, self.address))
        if pair is not None and pair.failures >= settings.LOGIN_PAIR_MAX_FAILURES:
            until = min(pair.last_failure_at + _backoff(pair.failures), pair.window_ends_at)
            if now < until:
                return Refusal(Outcome.PAIR_LIMITED, until)
        return None

    def failed(self) -> None:
        """The password check failed: count it, log it, record a new attack on the account."""
        counts = count_failure(self.account, self.address, timezone.now())
        self._log(Outcome.BAD_CREDENTIALS)
        if counts["account"] == settings.LOGIN_ACCOUNT_MAX_FAILURES:
            self._record_under_attack()

    def succeeded(self, user: User, response: HttpResponseBase) -> None:
        """A valid login: clear this pair only, and remember this browser for the account."""
        LoginFailures.objects.filter(account=self.account, address=self.address).delete()
        remember_device(self.request, response, user)

    def _record_under_attack(self) -> None:
        """Once per window: the upsert returns the threshold to exactly one failure."""
        users = self.named_users()
        if not users:
            return  # unknown names are limited the same way, but nothing to record
        with (
            audit_context(
                channel=CHANNELS[self.surface],
                actor_kind=ActorKind.SYSTEM,
                actor_label=SYSTEM_LABEL,
            ),
            audited_atomic(),
        ):
            for user in users:
                record_event(
                    LOGIN_ACCOUNT_UNDER_ATTACK,
                    Change("user", user.public_id, {"login_under_attack": [False, True]}),
                )

    def _log(self, outcome: Outcome) -> None:
        fields = {
            "event": "login_failed",
            "account_ref": self.account_ref,
            "ip_bucket": self.ip_bucket,
            "surface": str(self.surface),
            "outcome": str(outcome),
            "request_id": current_request_id(),
        }
        logger.warning(
            "login_failed account_ref=%s ip_bucket=%s surface=%s outcome=%s",
            fields["account_ref"],
            fields["ip_bucket"],
            fields["surface"],
            fields["outcome"],
            extra={"fields": fields},
        )


def _device_signer(user: User) -> signing.TimestampSigner:
    return signing.TimestampSigner(
        salt=f"{DEVICE_SALT}:{user.public_id}:{user.password}", algorithm="sha256"
    )


def _device_tokens(request: HttpRequest | Request) -> list[str]:
    raw: str = request.COOKIES.get(settings.KNOWN_DEVICE_COOKIE_NAME, "")
    return [token for token in raw.split(DEVICE_SEPARATOR) if token][:KNOWN_DEVICES_PER_BROWSER]


def _signed_for(token: str, user: User) -> bool:
    try:
        value = _device_signer(user).unsign(token, max_age=settings.KNOWN_DEVICE_COOKIE_AGE)
    except signing.BadSignature:  # also SignatureExpired
        return False
    return value == DEVICE_VALUE


def remember_device(request: HttpRequest | Request, response: HttpResponseBase, user: User) -> None:
    """Put a fresh entry for `user` first and keep the browser's other accounts after it."""
    others = [token for token in _device_tokens(request) if not _signed_for(token, user)]
    tokens = [_device_signer(user).sign(DEVICE_VALUE), *others][:KNOWN_DEVICES_PER_BROWSER]
    response.set_cookie(
        settings.KNOWN_DEVICE_COOKIE_NAME,
        DEVICE_SEPARATOR.join(tokens),
        max_age=settings.KNOWN_DEVICE_COOKIE_AGE,
        path="/",
        secure=settings.KNOWN_DEVICE_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )


def clear_account(username: str) -> int:
    """Delete every counter of the account (its pairs and its own row). For services only."""
    deleted, _ = LoginFailures.objects.filter(account=account_key(username)).delete()
    return deleted


def prune(now: datetime) -> int:
    """Delete the counters whose window has ended: they count nothing any more."""
    deleted, _ = LoginFailures.objects.filter(window_ends_at__lte=now).delete()
    return deleted
