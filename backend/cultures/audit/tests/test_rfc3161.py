"""The RFC 3161 client of a qualified timestamp provider (#283), against a TSA of our own.

The provider is a test TSA built here: a CA and a TSA certificate generated for the run,
and `openssl ts -reply` answering real HTTP requests on 127.0.0.1. Nothing reaches the
network and no key is kept in the repository. Each way an answer can be wrong has a mode
of the TSA, and each is refused with its own message before anything is stored.
"""

import datetime
import hashlib
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import rfc3161_client as tsp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from pytest_django.fixtures import Settings

from cultures.audit.models import ChainAnchor
from cultures.audit.timestamping import (
    VERIFIED,
    Rfc3161Authority,
    Unavailable,
    token_problem,
)

# The rows to anchor, and the test event types they use (test_anchors.py).
from .test_anchors import chain_types, member, written

__all__ = ["chain_types", "member", "written"]

pytestmark = pytest.mark.django_db

HEAD = hashlib.sha256(b"the head of a chain").digest()
REJECTION = bytes.fromhex("30053003020102")  # TimeStampResp, status rejection, no token
BACKEND = "cultures.audit.timestamping.Rfc3161Authority"
NOW = datetime.datetime.now(datetime.UTC)


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _certificate(
    subject: str,
    key: ec.EllipticCurvePrivateKey,
    issuer: str,
    issuer_key: ec.EllipticCurvePrivateKey,
) -> x509.Certificate:
    """A CA when it signs itself, else a TSA certificate with the critical EKU timeStamping."""
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - datetime.timedelta(days=1))
        .not_valid_after(NOW + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=subject == issuer, path_length=None), critical=True)
    )
    if subject != issuer:
        eku = x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING])
        builder = builder.add_extension(eku, critical=True)
    return builder.sign(issuer_key, hashes.SHA256())


def _pem(certificate: x509.Certificate) -> bytes:
    return certificate.public_bytes(serialization.Encoding.PEM)


def _root(path: Path, common_name: str) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(ec.SECP256R1())
    root = _certificate(common_name, key, common_name, key)
    path.write_bytes(_pem(root))
    return key, root


@dataclass
class LocalTsa:
    """A TSA on 127.0.0.1. `mode` says how it answers the next requests."""

    folder: Path
    url: str = ""
    mode: str = "granted"
    requests: list[bytes] = field(default_factory=list)

    @property
    def roots(self) -> str:
        return str(self.folder / "roots.pem")

    def reply(self, query: bytes) -> bytes:
        self.requests.append(query)
        if self.mode == "rejection":
            return REJECTION
        if self.mode == "garbage":
            return b"<html>not a timestamp</html>"
        if self.mode == "other_imprint":
            # The same request with another message imprint: our nonce, not our hash.
            ours = hashlib.sha256(HEAD).digest()
            query = query.replace(ours, hashlib.sha256(b"something else").digest())
        if self.mode == "other_nonce":
            query = (
                tsp.TimestampRequestBuilder()
                .data(HEAD)
                .hash_algorithm(tsp.HashAlgorithm.SHA256)
                .build()
                .as_bytes()
            )
        return self._sign(query)

    def _sign(self, query: bytes) -> bytes:
        (self.folder / "query.tsq").write_bytes(query)
        subprocess.run(  # noqa: S603 (fixed arguments, files of this test)
            [  # noqa: S607 (openssl of the image)
                "openssl",
                "ts",
                "-reply",
                "-config",
                str(self.folder / "tsa.cnf"),
                "-queryfile",
                str(self.folder / "query.tsq"),
                "-signer",
                str(self.folder / "tsa.pem"),
                "-inkey",
                str(self.folder / "tsa.key"),
                "-out",
                str(self.folder / "reply.tsr"),
            ],
            check=True,
            capture_output=True,
        )
        return (self.folder / "reply.tsr").read_bytes()


def _write_tsa(folder: Path) -> None:
    """The CA, the TSA certificate and key, and the openssl TSA configuration."""
    ca_key, _ = _root(folder / "roots.pem", "Test timestamp CA")
    tsa_key = ec.generate_private_key(ec.SECP256R1())
    certificate = _certificate("Test TSA", tsa_key, "Test timestamp CA", ca_key)
    (folder / "tsa.pem").write_bytes(_pem(certificate))
    (folder / "tsa.key").write_bytes(
        tsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (folder / "serial").write_text("01\n")
    (folder / "tsa.cnf").write_text(
        "[ tsa ]\ndefault_tsa = test\n[ test ]\n"
        f"serial = {folder / 'serial'}\ncrypto_device = builtin\nsigner_digest = sha256\n"
        "default_policy = 1.2.3.4.1\ndigests = sha256, sha512\naccuracy = secs:1\n"
        "ess_cert_id_alg = sha256\n"
    )


@pytest.fixture
def tsa(tmp_path: Path) -> Iterator[LocalTsa]:
    _write_tsa(tmp_path)
    local = LocalTsa(tmp_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            if local.mode == "server_error":
                self.send_error(500)
                return
            answer = local.reply(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/timestamp-reply")
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local.url = f"http://127.0.0.1:{server.server_address[1]}/tsr"
    yield local
    server.shutdown()


def client(tsa: LocalTsa, **changes: str) -> Rfc3161Authority:
    options: dict[str, Any] = {"url": tsa.url, "ca_file": tsa.roots, "name": "Test TSA", **changes}
    return Rfc3161Authority(**options)


def test_a_granted_answer_is_kept_and_verifies_again(tsa: LocalTsa) -> None:
    token = client(tsa).stamp(HEAD)
    assert token.authority == "Test TSA"
    assert token.time is not None
    assert abs(token.time - NOW) < datetime.timedelta(minutes=5)
    assert token_problem(token.token, HEAD, tsa.roots) is None
    # The request asked for SHA-256 over the head, with a nonce and the TSA certificate.
    request_answer = tsp.decode_timestamp_response(token.token)
    assert request_answer.tst_info.message_imprint.message == hashlib.sha256(HEAD).digest()
    assert request_answer.tst_info.nonce is not None


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        pytest.param("rejection", "refused: status 2", id="a-refusal"),
        pytest.param("garbage", "sent no timestamp response", id="not-a-timestamp"),
        pytest.param("other_imprint", "Mismatch between messages", id="another-hash"),
        pytest.param("other_nonce", "Nonce mismatch", id="another-nonce"),
        pytest.param("server_error", "could not be reached", id="a-server-error"),
    ],
)
def test_a_wrong_answer_is_refused_with_its_own_message(
    tsa: LocalTsa, mode: str, message: str
) -> None:
    tsa.mode = mode
    with pytest.raises(Unavailable, match=message):
        client(tsa).stamp(HEAD)


def test_a_tsa_outside_the_bundle_is_refused(tsa: LocalTsa, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _root(other / "roots.pem", "Another CA")
    with pytest.raises(Unavailable, match="Error while verifying certificates"):
        client(tsa, ca_file=str(other / "roots.pem")).stamp(HEAD)


def test_an_unreachable_provider_is_unavailable() -> None:
    with pytest.raises(Unavailable, match="could not be reached"):
        Rfc3161Authority(url="http://127.0.0.1:9/tsr", ca_file="/dev/null", timeout=2).stamp(HEAD)


def test_basic_authentication_comes_from_a_secret_file(tsa: LocalTsa, tmp_path: Path) -> None:
    secret = tmp_path / "password"
    secret.write_text("s3cret\n")
    authority = client(tsa, username="lab", password_file=str(secret))
    assert authority._headers()["Authorization"] == "Basic bGFiOnMzY3JldA=="


@pytest.mark.parametrize(
    ("options", "message"),
    [
        pytest.param({"ca_file": "/x.pem"}, "provider's http", id="no-url"),
        pytest.param({"url": "https://tsa.example.org"}, "provider's roots", id="no-roots"),
    ],
)
def test_the_client_needs_a_url_and_roots(options: dict[str, Any], message: str) -> None:
    with pytest.raises(ImproperlyConfigured, match=message):
        Rfc3161Authority(**options)


def test_a_stored_token_no_longer_matches_a_changed_head(tsa: LocalTsa) -> None:
    token = client(tsa).stamp(HEAD).token
    problem = token_problem(token, hashlib.sha256(b"rewritten").digest(), tsa.roots)
    assert problem is not None
    assert "Mismatch between messages" in problem


def test_a_tampered_stored_token_is_refused(tsa: LocalTsa) -> None:
    token = bytearray(client(tsa).stamp(HEAD).token)
    token[-40] ^= 0xFF  # inside the signature
    problem = token_problem(bytes(token), HEAD, tsa.roots)
    assert problem is not None


def test_a_token_is_checked_against_the_bundle_of_verify_time(
    tsa: LocalTsa, tmp_path: Path
) -> None:
    token = client(tsa).stamp(HEAD).token
    other = tmp_path / "other"
    other.mkdir()
    _root(other / "roots.pem", "Another CA")
    problem = token_problem(token, HEAD, str(other / "roots.pem"))
    assert problem is not None
    assert "Error while verifying certificates" in problem


@pytest.fixture
def anchored_by_tsa(tsa: LocalTsa, settings: Settings, written: None) -> LocalTsa:
    """Both chains anchored by the test TSA through the daily job."""
    settings.AUDIT_TIMESTAMP_AUTHORITY = {
        "BACKEND": BACKEND,
        "OPTIONS": {"url": tsa.url, "ca_file": tsa.roots, "name": "Test TSA"},
    }
    call_command("audit_chain_anchor", stdout=StringIO())
    assert {a.authority for a in ChainAnchor.objects.all()} == {"Test TSA"}
    return tsa


def verify_output() -> tuple[int, str]:
    out = StringIO()
    try:
        call_command("audit_chain_verify", stdout=out)
    except CommandError as error:
        return error.returncode or 1, out.getvalue()
    return 0, out.getvalue()


@pytest.mark.rule("R-AUDIT-04")
def test_the_daily_job_stores_tokens_that_the_verifier_checks(anchored_by_tsa: LocalTsa) -> None:
    code, output = verify_output()
    assert code == 0, output
    assert f"token of Test TSA: {VERIFIED}" in output


@pytest.mark.rule("R-AUDIT-04")
def test_the_verifier_fails_an_anchor_whose_token_the_bundle_no_longer_trusts(
    anchored_by_tsa: LocalTsa, settings: Settings, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    _root(other / "roots.pem", "Another CA")
    settings.AUDIT_TIMESTAMP_AUTHORITY["OPTIONS"]["ca_file"] = str(other / "roots.pem")
    code, output = verify_output()
    assert code == 1
    assert "anchor_token_invalid" in output
    assert "Error while verifying certificates" in output
