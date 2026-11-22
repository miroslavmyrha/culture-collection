"""A security key in software for the tests (#176): it answers WebAuthn ceremonies the way a
browser with a hardware key does ("none" attestation, ES256), so py_webauthn verifies real
signatures. The origin, the counter and the challenge can be set wrong on purpose."""

import base64
import hashlib
import json
import os
import struct
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

UP, UV, AT = 0x01, 0x04, 0x40  # user present, user verified, attested credential data


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SoftKey:
    def __init__(self, rp_id: str = "localhost", origin: str = "http://localhost") -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.count = 0

    def public_cose_key(self) -> bytes:
        """The public key as the server stores it (COSE)."""
        return self._cose_key()

    def _cose_key(self) -> bytes:
        numbers = self.private.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _client_data(self, kind: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin or self.origin}
        ).encode()

    def _rp_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def register(self, options: dict[str, Any], *, origin: str | None = None) -> dict[str, Any]:
        """The answer to navigator.credentials.create with these options."""
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        auth_data = (
            self._rp_hash()
            + bytes([UP | UV | AT])
            + struct.pack(">I", self.count)
            + bytes(16)  # aaguid
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation),
                "transports": ["usb"],
            },
            "clientExtensionResults": {},
        }

    def sign(
        self, options: dict[str, Any], *, origin: str | None = None, count: int | None = None
    ) -> dict[str, Any]:
        """The answer to navigator.credentials.get: the counter goes up unless `count` is given."""
        self.count = self.count + 1 if count is None else count
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = self._rp_hash() + bytes([UP | UV]) + struct.pack(">I", self.count)
        signature = self.private.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }
