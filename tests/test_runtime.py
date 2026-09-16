"""Runtime connections in the Python SDK.

WHAT THIS HAS TO PROVE:

* The SDK's DPoP matches the shared vectors every other language checks
  against: the same thumbprint, the same ath, the same wire shape.
* One refresh at a time, and the rotated refresh token is stored BEFORE any
  caller receives an access token.
* A terminal failure (reuse, revoked) is raised with its remediation and never
  retried into something else.
* One client, one identity: a key and a connection together are refused.

Run:  python -m unittest discover -s tests
(the "runtime" extra must be installed: pip install "centcom[runtime]")
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from centcom.runtime.dpop import DpopKey, access_token_hash, create_proof, jwk_thumbprint
    from centcom.runtime.token_provider import (
        FileCredentialStore,
        InMemoryCredentialStore,
        RuntimeCredentialError,
        RuntimeTokenProvider,
        StoredCredential,
    )
    from centcom.client import CentcomClient
    from centcom.runtime.auth import RuntimeAuth, broker_transport
except ImportError as error:  # pragma: no cover - optional extra missing
    raise unittest.SkipTest(f'the "runtime" extra is not installed: {error}')

VECTORS_PATH = Path(__file__).resolve().parents[3] / "packages" / "protocol" / "test-vectors" / "runtime" / "dpop-vectors.json"


class DpopVectorTests(unittest.TestCase):
    def test_matches_the_shared_vectors(self) -> None:
        if not VECTORS_PATH.exists():  # pragma: no cover - published package
            self.skipTest("shared vectors are not part of the published package")
        vectors = json.loads(VECTORS_PATH.read_text())
        self.assertEqual(jwk_thumbprint(vectors["key"]["public_jwk"]), vectors["key"]["jkt"])
        self.assertEqual(access_token_hash(vectors["access_token"]["value"]), vectors["access_token"]["ath"])

        key = _key_from_vector(vectors)
        self.assertEqual(key.thumbprint, vectors["key"]["jkt"], "the key derived from d has the vector's thumbprint")

        proof = create_proof(
            key,
            "post",
            "https://api.contro1.test/api/centcom/v1/requests?x=1#f",
            access_token=vectors["access_token"]["value"],
            nonce="n",
        )
        header, payload, signature = proof.split(".")
        decoded_header = json.loads(_b64decode(header))
        decoded_payload = json.loads(_b64decode(payload))
        self.assertEqual(decoded_header["typ"], "dpop+jwt")
        self.assertEqual(decoded_header["alg"], "ES256")
        self.assertEqual(decoded_payload["htm"], "POST")
        self.assertEqual(decoded_payload["htu"], "https://api.contro1.test/api/centcom/v1/requests")
        self.assertEqual(decoded_payload["ath"], vectors["access_token"]["ath"])
        self.assertEqual(len(_b64decode(signature)), 64, "ES256 signatures are raw R||S")

        # The signature verifies with the public key, like the server's check.
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        raw = _b64decode(signature)
        der = utils.encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        key.private_key.public_key().verify(der, f"{header}.{payload}".encode("ascii"), ec.ECDSA(hashes.SHA256()))

    def test_relative_urls_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            create_proof(DpopKey.generate(), "GET", "/relative")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _key_from_vector(vectors: dict) -> DpopKey:
    from cryptography.hazmat.primitives.asymmetric import ec

    jwk = vectors["key"]["private_jwk"]
    private_value = int.from_bytes(_b64decode(jwk["d"]), "big")
    return DpopKey(ec.derive_private_key(private_value, ec.SECP256R1()))


class _AuthorizationServer(BaseHTTPRequestHandler):
    """A token endpoint that really rotates and really checks the proof."""

    state = {"current": "ccrt_1", "refreshes": 0, "reuse": False, "nonce": "n1", "require_nonce": True}

    def log_message(self, *args):  # noqa: D401 - quiet test output
        pass

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("content-length", 0))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        proof = self.headers.get("DPoP")
        state = _AuthorizationServer.state
        if not proof:
            return self._json(400, {"error": "invalid_dpop_proof"})
        payload = json.loads(_b64decode(proof.split(".")[1]))
        if state["require_nonce"] and payload.get("nonce") != state["nonce"]:
            return self._json(400, {"error": "use_dpop_nonce"})
        if state["reuse"] or form.get("refresh_token", [""])[0] != state["current"]:
            return self._json(400, {
                "error": "invalid_grant",
                "contro1_reason": "refresh_reuse",
                "remediation": {"code": "CONNECTION_NOT_ACTIVE", "public_message": "This connection was suspended.", "next_step": "Connect this computer again."},
            })
        state["refreshes"] += 1
        state["current"] = f"ccrt_{state['refreshes'] + 1}"
        resource = form.get("resource", ["api"])[0]
        return self._json(200, {
            "access_token": f"at_{resource}_{state['refreshes']}",
            "token_type": "DPoP",
            "expires_in": 300,
            "refresh_token": state["current"],
            "agent_id": "agt_1",
            "enrollment_id": "enr_1",
        })

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("dpop-nonce", _AuthorizationServer.state["nonce"])
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class TokenProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        _AuthorizationServer.state = {"current": "ccrt_1", "refreshes": 0, "reuse": False, "nonce": "n1", "require_nonce": True}
        self.server = HTTPServer(("127.0.0.1", 0), _AuthorizationServer)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _credential(self) -> StoredCredential:
        return StoredCredential("enr_1", "agt_1", "ccrt_1", DpopKey.generate().to_pem())

    def test_concurrent_callers_cause_one_refresh(self) -> None:
        provider = RuntimeTokenProvider(self.api_url, InMemoryCredentialStore(self._credential()))
        with ThreadPoolExecutor(max_workers=16) as pool:
            tokens = list(pool.map(lambda _: provider.access_token("api"), range(32)))
        self.assertEqual(len(set(tokens)), 1)
        self.assertEqual(_AuthorizationServer.state["refreshes"], 1, "32 callers, one refresh (and one nonce retry)")
        self.assertTrue(provider.access_token("mcp").startswith("at_mcp_"))
        self.assertEqual(_AuthorizationServer.state["refreshes"], 2, "a second audience needs its own token")

    def test_rotated_token_is_persisted_before_the_caller_sees_a_token(self) -> None:
        with TemporaryDirectory() as directory:
            path = os.path.join(directory, "credential.json")
            store = FileCredentialStore(path)
            store.save(self._credential())
            provider = RuntimeTokenProvider(self.api_url, store)
            token = provider.access_token("api")
            persisted = json.loads(Path(path).read_text())
            self.assertEqual(persisted["refresh_token"], _AuthorizationServer.state["current"])
            self.assertNotIn(token, json.dumps(persisted), "an access token is never persisted")
            # A restart continues from the stored token.
            self.assertTrue(RuntimeTokenProvider(self.api_url, FileCredentialStore(path)).access_token("api"))

    def test_reuse_is_terminal_with_a_remediation(self) -> None:
        _AuthorizationServer.state["reuse"] = True
        provider = RuntimeTokenProvider(self.api_url, InMemoryCredentialStore(self._credential()))
        with self.assertRaises(RuntimeCredentialError) as caught:
            provider.access_token("api")
        self.assertEqual(caught.exception.kind, "reuse_suspended")
        self.assertTrue(caught.exception.terminal)
        self.assertEqual(caught.exception.remediation["code"], "CONNECTION_NOT_ACTIVE")

    def test_authorize_headers_bind_the_request(self) -> None:
        provider = RuntimeTokenProvider(self.api_url, InMemoryCredentialStore(self._credential()))
        headers = provider.authorize_headers("GET", "https://api.contro1.test/api/centcom/v1/runtime/status")
        self.assertTrue(headers["Authorization"].startswith("DPoP at_api_"))
        payload = json.loads(_b64decode(headers["DPoP"].split(".")[1]))
        self.assertEqual(payload["htm"], "GET")
        self.assertEqual(payload["htu"], "https://api.contro1.test/api/centcom/v1/runtime/status")
        self.assertEqual(payload["ath"], access_token_hash(headers["Authorization"][len("DPoP "):]))
        self.assertEqual(payload["nonce"], "n1", "the server's nonce is carried")


class ClientIdentityTests(unittest.TestCase):
    def test_one_client_one_identity(self) -> None:
        provider = RuntimeTokenProvider("https://api.contro1.test", InMemoryCredentialStore(None))
        with self.assertRaises(ValueError):
            CentcomClient()
        with self.assertRaises(ValueError):
            CentcomClient(api_key="cc_live_x", auth=RuntimeAuth(provider))
        CentcomClient(auth=RuntimeAuth(provider))

    def test_named_pipes_say_what_to_use_instead(self) -> None:
        with self.assertRaises(NotImplementedError):
            broker_transport("npipe:////./pipe/contro1-ep-x")
        with self.assertRaises(ValueError):
            broker_transport("https://api.contro1.test")


if __name__ == "__main__":
    unittest.main()
