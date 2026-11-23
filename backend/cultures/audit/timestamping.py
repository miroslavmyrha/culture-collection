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
- `Rfc3161Authority` is the client of a real provider (#283): an RFC 3161 request
  over the head's hash (SHA-256, a nonce, the TSA certificate asked for), sent by
  HTTP POST to AUDIT_TIMESTAMP_URL. The answer is kept only once it verifies
  (rfc3161-client): status granted, the nonce and the message imprint ours, the
  signature and the TSA certificate chain trusted by AUDIT_TIMESTAMP_CA_FILE (the
  provider's roots and intermediates, never the system store), the TSA
  certificate with the critical extended key usage timeStamping. Anything else
  raises `Unavailable`: the day stays unanchored and the job alerts. Only the
  hash leaves the system.

Reading a token back is the other half: `token_problem()` verifies a stored token
again against the bundle configured at verify time, so `manage.py
audit_chain_verify` reports an anchor whose token no longer verifies, and says so
when no bundle is configured instead of claiming more than it checked.
"""

import base64
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

import rfc3161_client as tsp
from cryptography import x509
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


QUERY = "application/timestamp-query"
REPLY = "application/timestamp-reply"


def _trust(ca_file: str) -> tuple[list[x509.Certificate], list[x509.Certificate]]:
    """The provider's roots (self-signed) and intermediates from one PEM bundle."""
    try:
        found = x509.load_pem_x509_certificates(Path(ca_file).read_bytes())
    except (OSError, ValueError) as problem:
        raise ImproperlyConfigured(f"AUDIT_TIMESTAMP_CA_FILE={ca_file!r}: {problem}") from None
    roots = [c for c in found if c.issuer == c.subject]
    if not roots:
        raise ImproperlyConfigured(f"AUDIT_TIMESTAMP_CA_FILE={ca_file!r} holds no root")
    return roots, [c for c in found if c.issuer != c.subject]


def _verifier(ca_file: str, builder: tsp.VerifierBuilder) -> tsp.Verifier:
    roots, intermediates = _trust(ca_file)
    for root in roots:
        builder = builder.add_root_certificate(root)
    for intermediate in intermediates:
        builder = builder.add_intermediate_certificate(intermediate)
    return builder.build()


class Rfc3161Authority:
    """A qualified trust service provider's RFC 3161 timestamp service (#283).

    OPTIONS: url and ca_file (required), name (the anchor's authority column, the
    URL's host by default), timeout in seconds, username and password_file for
    HTTP basic authentication when the provider asks for it.
    """

    def __init__(
        self,
        *,
        url: str = "",
        ca_file: str = "",
        name: str = "",
        timeout: float = 30,
        username: str = "",
        password_file: str = "",
    ) -> None:
        if not url.startswith("https://") and not url.startswith("http://"):
            raise ImproperlyConfigured("AUDIT_TIMESTAMP_URL must be the provider's http(s) URL")
        if not ca_file:
            raise ImproperlyConfigured("AUDIT_TIMESTAMP_CA_FILE must name the provider's roots")
        self.url, self.ca_file, self.timeout = url, ca_file, timeout
        self.name = name or urlsplit(url).hostname or url
        self.username, self.password_file = username, password_file

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": QUERY, "Accept": REPLY}
        if self.username:
            password = Path(self.password_file).read_text(encoding="utf-8").strip()
            pair = f"{self.username}:{password}".encode()
            headers["Authorization"] = "Basic " + base64.b64encode(pair).decode()
        return headers

    def _post(self, body: bytes) -> bytes:
        request = urllib.request.Request(  # noqa: S310 (the URL is checked above)
            self.url, data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as answer:  # noqa: S310
                return bytes(answer.read())
        except (urllib.error.URLError, OSError) as problem:
            raise Unavailable(f"{self.name} could not be reached: {problem}") from None

    def stamp(self, digest: bytes) -> Token:
        request = (
            tsp.TimestampRequestBuilder()
            .data(digest)
            .hash_algorithm(tsp.HashAlgorithm.SHA256)
            .build()
        )
        raw = self._post(request.as_bytes())
        try:
            response = tsp.decode_timestamp_response(raw)
        except ValueError:
            raise Unavailable(f"{self.name} sent no timestamp response") from None
        if response.status != tsp.PKIStatus.GRANTED:
            said = "; ".join(response.status_string) or "no reason given"
            raise Unavailable(f"{self.name} refused: status {response.status} ({said})")
        verifier = _verifier(self.ca_file, tsp.VerifierBuilder.from_request(request))
        try:
            verifier.verify_message(response, digest)
        except tsp.VerificationError as problem:
            raise Unavailable(f"the answer of {self.name} did not verify: {problem}") from None
        return Token(self.name, response.as_bytes(), response.tst_info.gen_time)


FAKE_NOTE = "a token of the fake authority: no evidence of anything"
NOT_VERIFIED = "not verified: AUDIT_TIMESTAMP_CA_FILE names no bundle to verify the tokens with"
VERIFIED = "every token verified against AUDIT_TIMESTAMP_CA_FILE"


def verify_bundle() -> str:
    """The trust bundle tokens are verified with now: may hold the provider's old roots too."""
    options: dict[str, Any] = settings.AUDIT_TIMESTAMP_AUTHORITY.get("OPTIONS", {})
    return str(options.get("ca_file") or "")


def token_problem(token: bytes, head_hash: bytes, ca_file: str) -> str | None:
    """What is wrong with a stored token over this head, or None when it verifies."""
    try:
        response = tsp.decode_timestamp_response(token)
    except ValueError:
        return "the stored token is not a timestamp response"
    try:
        _verifier(ca_file, tsp.VerifierBuilder()).verify_message(response, head_hash)
    except tsp.VerificationError as problem:
        return f"the token does not verify: {problem}"
    return None


def token_note(stamped_by: str) -> str:
    """What this build says about the tokens of one authority."""
    if stamped_by == FAKE:
        return FAKE_NOTE
    return VERIFIED if verify_bundle() else NOT_VERIFIED
