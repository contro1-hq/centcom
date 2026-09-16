"""RuntimeTokenProvider: DPoP access tokens for one owner-approved connection.

Rules it never breaks:

* One refresh at a time. Concurrent callers wait for the same refresh.
* The rotated refresh token is stored BEFORE any caller receives the new access
  token, because a crash between the two loses the only usable credential.
* Terminal failures (revoked, reuse, expired approval) are raised with the
  server's remediation and never replaced by another credential.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

import httpx

from .dpop import DpopKey, create_proof

DEVICE_AUTHORIZATION_PATH = "/api/centcom/v1/runtime/oauth/device_authorization"
TOKEN_PATH = "/api/centcom/v1/runtime/oauth/token"
REVOKE_PATH = "/api/centcom/v1/runtime/oauth/revoke"
CLIENT_ID = "contro1-runtime"

TERMINAL_KINDS = {"revoked", "reuse_suspended", "approval_expired", "not_connected", "declined", "expired"}


class RuntimeCredentialError(Exception):
    """A runtime credential failure, with the remediation when the server sent one."""

    def __init__(self, message: str, kind: str, remediation: Optional[dict] = None, interval: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.remediation = remediation
        self.interval = interval

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS


@dataclass
class StoredCredential:
    enrollment_id: str
    agent_id: str
    refresh_token: str
    private_key_pem: str
    approval_expires_at: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, raw: str) -> "StoredCredential":
        return cls(**json.loads(raw))


class CredentialStore:
    """Durable when save() returns."""

    def load(self) -> Optional[StoredCredential]:  # pragma: no cover - interface
        raise NotImplementedError

    def save(self, credential: StoredCredential) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class InMemoryCredentialStore(CredentialStore):
    def __init__(self, credential: Optional[StoredCredential] = None):
        self._credential = credential

    def load(self) -> Optional[StoredCredential]:
        return self._credential

    def save(self, credential: StoredCredential) -> None:
        self._credential = credential


class FileCredentialStore(CredentialStore):
    """A 0600 file. One process per connection, or an external lock."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> Optional[StoredCredential]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return StoredCredential.from_json(handle.read())
        except FileNotFoundError:
            return None

    def save(self, credential: StoredCredential) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        temp = f"{self.path}.{os.getpid()}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        handle = os.open(temp, flags, 0o600)
        try:
            os.write(handle, credential.to_json().encode("utf-8"))
            os.fsync(handle)
        finally:
            os.close(handle)
        os.replace(temp, self.path)


class RuntimeTokenProvider:
    def __init__(
        self,
        api_url: str,
        store: CredentialStore,
        *,
        client: Optional[httpx.Client] = None,
        now: Callable[[], float] = time.time,
        lock: Optional[Any] = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.store = store
        self._client = client or httpx.Client(timeout=30.0)
        self._now = now
        self._lock = lock or threading.Lock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._nonce: Optional[str] = None
        self._key: Optional[DpopKey] = None
        self.refresh_count = 0

    # -- keys and nonces ---------------------------------------------------

    def dpop_key(self) -> DpopKey:
        if self._key is None:
            credential = self.store.load()
            if credential is None:
                raise RuntimeCredentialError("This connection has no stored credential.", "not_connected")
            self._key = DpopKey.from_pem(credential.private_key_pem)
        return self._key

    def observe_nonce(self, headers: Mapping[str, str]) -> None:
        nonce = headers.get("dpop-nonce") or headers.get("DPoP-Nonce")
        if nonce:
            self._nonce = nonce

    def invalidate(self, resource: Optional[str] = None) -> None:
        if resource:
            self._cache.pop(resource, None)
        else:
            self._cache.clear()

    # -- tokens ------------------------------------------------------------

    def access_token(self, resource: str = "api") -> str:
        cached = self._cache.get(resource)
        if cached and cached["expires_at"] - 60 > self._now():
            return cached["token"]
        with self._lock:
            cached = self._cache.get(resource)
            if cached and cached["expires_at"] - 60 > self._now():
                return cached["token"]
            credential = self.store.load()
            if credential is None:
                raise RuntimeCredentialError("This connection has no stored credential.", "not_connected")
            self._key = DpopKey.from_pem(credential.private_key_pem)
            self.refresh_count += 1
            body = self.token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": credential.refresh_token,
                    "client_id": CLIENT_ID,
                    "resource": resource,
                }
            )
            if body.get("refresh_token"):
                credential.refresh_token = body["refresh_token"]
                # Durable before any caller sees the new access token.
                self.store.save(credential)
            self._cache[resource] = {"token": body["access_token"], "expires_at": self._now() + float(body.get("expires_in", 300))}
            return body["access_token"]

    def token_request(self, form: Mapping[str, str]) -> dict:
        key = self.dpop_key()
        url = f"{self.api_url}{TOKEN_PATH}"
        for attempt in range(2):
            try:
                response = self._client.post(
                    url,
                    data=dict(form),
                    headers={"DPoP": create_proof(key, "POST", url, nonce=self._nonce)},
                )
            except httpx.HTTPError as error:
                raise RuntimeCredentialError(f"Contro1 is not reachable: {error}", "network") from error
            self.observe_nonce(response.headers)
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if response.status_code == 200:
                return payload
            if payload.get("error") == "use_dpop_nonce" and attempt == 0:
                continue
            raise _classify(payload)
        raise RuntimeCredentialError("The token endpoint kept asking for a nonce.", "server")

    def authorize_headers(self, method: str, url: str, resource: str = "api") -> Dict[str, str]:
        token = self.access_token(resource)
        return {
            "Authorization": f"DPoP {token}",
            "DPoP": create_proof(self.dpop_key(), method, url, access_token=token, nonce=self._nonce),
        }


def _classify(payload: Mapping[str, Any]) -> RuntimeCredentialError:
    remediation = payload.get("remediation")
    reason = payload.get("contro1_reason") or ""
    message = str(payload.get("error_description") or payload.get("error") or "token request failed")
    error = payload.get("error")
    interval = payload.get("interval")
    if error == "authorization_pending":
        return RuntimeCredentialError(message, "pending", remediation, interval)
    if error == "slow_down":
        return RuntimeCredentialError(message, "slow_down", remediation, interval)
    if error == "access_denied":
        return RuntimeCredentialError(message, "declined", remediation)
    if error == "expired_token":
        return RuntimeCredentialError(message, "expired", remediation)
    if reason in ("refresh_reuse", "refresh_key_mismatch"):
        return RuntimeCredentialError(message, "reuse_suspended", remediation)
    if reason in ("approval_expired", "refresh_expired"):
        return RuntimeCredentialError(message, "approval_expired", remediation)
    if error == "invalid_grant":
        return RuntimeCredentialError(message, "revoked", remediation)
    return RuntimeCredentialError(message, "server", remediation)
