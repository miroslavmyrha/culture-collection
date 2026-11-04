"""The timestamp authority that stamps a chain's head (ADR 0009, #175).

ADR 0009, Decision, Tamper evidence: "Once a day the head of the chain gets a
qualified electronic timestamp from a qualified trust service provider (eIDAS,
Regulation (EU) No 910/2014, Article 41), which carries a legal presumption of
its date and of the integrity of the data it covers. Someone who can edit rows
can recompute the chain, but the stamped heads then no longer match."

A qualified timestamp is a paid service from an external provider (ADR 0009,
Consequences), so the client is behind a setting:

    AUDIT_TIMESTAMP_AUTHORITY = {"BACKEND": "<dotted path>", "OPTIONS": {...}}

- `NoAuthority` is the default, in production too: it stamps nothing and raises
  `Unavailable`, so a deployment without a contracted provider leaves its days
  unanchored and the daily job alerts on its exit code. Nothing waits for the
  authority and no write ever does: `manage.py audit_chain_anchor` runs on its
  own, after the writes it covers.
- `FakeAuthority` is for development and tests. Its token says what it is in its
  first bytes and its anchors carry the authority "fake", so nobody can mistake
  one for evidence. Production refuses it at startup
  (`config/settings/production.py`).
- A real provider's client is not written here. An RFC 3161 request and response
  are DER-encoded ASN.1, no provider is contracted and no verifier is installed
  (`cryptography`, `asn1crypto` and `rfc3161ng` are all absent from the image),
  so writing one from memory would be guesswork. What the operator must set up
  is in ADR 0009's amendment of 2026-11-04.

Reading a token back is the other half, and the same library is missing, so
`token_note()` says for every token whether it was verified here. The verifying
command prints that note instead of claiming more than it checked.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from django.utils.module_loading import import_string

FAKE = "fake"  # the authority column of an anchor made by FakeAuthority
FAKE_PREFIX = b"not-a-qualified-timestamp:"


class Unavailable(RuntimeError):
    """The authority could not be reached or refused. The head stays unanchored."""


@dataclass(frozen=True)
class Token:
    """One authority's answer, kept byte for byte."""

    authority: str  # who stamped it, for the anchor's authority column
    token: bytes  # the answer as it came
    time: datetime | None  # the time the authority asserts, when the client can read it


@runtime_checkable
class TimestampAuthority(Protocol):
    def stamp(self, digest: bytes) -> Token:
        """Stamp a chain head's digest, or raise Unavailable."""


class NoAuthority:
    """The default: no provider is configured, so no day is anchored."""

    def __init__(self, **options: Any) -> None:
        self.options = options

    def stamp(self, digest: bytes) -> Token:
        raise Unavailable(
            "no timestamp authority is configured: point AUDIT_TIMESTAMP_BACKEND at a"
            " qualified trust service provider's client (ADR 0009)"
        )


class FakeAuthority:
    """Development and tests: a token that says it is not a qualified one."""

    def __init__(self, **options: Any) -> None:
        self.options = options

    def stamp(self, digest: bytes) -> Token:
        now = timezone.now()
        token = FAKE_PREFIX + digest.hex().encode() + b":" + now.isoformat().encode()
        return Token(FAKE, token, now)


def authority() -> TimestampAuthority:
    """The configured client. Built per call: the job runs once a day."""
    configured = settings.AUDIT_TIMESTAMP_AUTHORITY
    path = configured.get("BACKEND")
    if not path:
        raise ImproperlyConfigured("AUDIT_TIMESTAMP_AUTHORITY needs a BACKEND")
    built = import_string(path)(**configured.get("OPTIONS", {}))
    if not isinstance(built, TimestampAuthority):
        raise ImproperlyConfigured(f"{path} has no stamp(digest) method")
    return built


NOT_VERIFIED = (
    "not verified here: no RFC 3161 verifier is installed, only the stored chain was checked"
)
FAKE_NOTE = "a token of the fake authority: no evidence of anything"


def token_note(stamped_by: str) -> str:
    """What this build can say about a token's own signature, never more."""
    return FAKE_NOTE if stamped_by == FAKE else NOT_VERIFIED
