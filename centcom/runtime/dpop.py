"""DPoP (RFC 9449) for Contro1 runtime connections.

ES256 proofs with raw R||S signatures, RFC 7638 thumbprints: the same wire
format the server, the Go service, and the JavaScript SDK use, checked against
the shared test vectors.

Needs the `cryptography` extra:  pip install "centcom[runtime]"
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

try:  # pragma: no cover - import guard
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
except ImportError as error:  # pragma: no cover - import guard
    raise ImportError(
        'Contro1 runtime connections need the "cryptography" package. '
        'Install it with: pip install "centcom[runtime]"'
    ) from error


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_json(value: Any) -> str:
    return b64url(json.dumps(value, separators=(",", ":"), sort_keys=False).encode("utf-8"))


@dataclass(frozen=True)
class DpopKey:
    """A P-256 key. The private key never leaves this object."""

    private_key: ec.EllipticCurvePrivateKey

    @classmethod
    def generate(cls) -> "DpopKey":
        return cls(ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_pem(cls, pem: str) -> "DpopKey":
        key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
            raise ValueError("a Contro1 connection key must be P-256")
        return cls(key)

    def to_pem(self) -> str:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")

    @property
    def public_jwk(self) -> dict:
        numbers = self.private_key.public_key().public_numbers()
        return {
            "kty": "EC",
            "crv": "P-256",
            "x": b64url(numbers.x.to_bytes(32, "big")),
            "y": b64url(numbers.y.to_bytes(32, "big")),
        }

    @property
    def thumbprint(self) -> str:
        return jwk_thumbprint(self.public_jwk)

    def sign_digest_raw(self, signing_input: bytes) -> bytes:
        der = self.private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = asym_utils.decode_dss_signature(der)
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def jwk_thumbprint(jwk: Mapping[str, str]) -> str:
    """RFC 7638: required members only, lexicographic order."""
    canonical = '{"crv":"%s","kty":"%s","x":"%s","y":"%s"}' % (jwk["crv"], jwk["kty"], jwk["x"], jwk["y"])
    return b64url(hashlib.sha256(canonical.encode("utf-8")).digest())


def access_token_hash(access_token: str) -> str:
    return b64url(hashlib.sha256(access_token.encode("ascii")).digest())


def create_proof(
    key: DpopKey,
    method: str,
    url: str,
    *,
    access_token: Optional[str] = None,
    nonce: Optional[str] = None,
    now: Optional[float] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> str:
    """One proof for one request. Query and fragment are not part of htu."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("htu must be an absolute http(s) URL")
    htu = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    payload: dict = {
        "htm": method.upper(),
        "htu": htu,
        "iat": int(now if now is not None else time.time()),
        "jti": b64url(os.urandom(18)),
    }
    if access_token:
        payload["ath"] = access_token_hash(access_token)
    if nonce:
        payload["nonce"] = nonce
    if extra:
        payload.update(extra)
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": key.public_jwk}
    signing_input = f"{_b64url_json(header)}.{_b64url_json(payload)}"
    signature = key.sign_digest_raw(signing_input.encode("ascii"))
    return f"{signing_input}.{b64url(signature)}"
