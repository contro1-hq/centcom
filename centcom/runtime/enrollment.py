"""Enrolling a Python-hosted agent, and cloud workload federation."""

from __future__ import annotations

import time
from typing import Optional

import httpx

from .dpop import DpopKey, create_proof
from .token_provider import (
    CLIENT_ID,
    DEVICE_AUTHORIZATION_PATH,
    CredentialStore,
    RuntimeCredentialError,
    RuntimeTokenProvider,
    StoredCredential,
)


def register_key_with_ticket(
    api_url: str,
    connection_ticket: str,
    item_id: str,
    *,
    key: Optional[DpopKey] = None,
    client: Optional[httpx.Client] = None,
) -> tuple:
    """Register this process's public key for one item of a connection."""
    key = key or DpopKey.generate()
    http = client or httpx.Client(timeout=30.0)
    url = f"{api_url.rstrip('/')}{DEVICE_AUTHORIZATION_PATH}"
    response = http.post(
        url,
        data={"connection_ticket": connection_ticket, "item_id": item_id, "client_id": CLIENT_ID},
        headers={"DPoP": create_proof(key, "POST", url)},
    )
    payload = response.json() if response.content else {}
    if response.status_code != 200:
        raise RuntimeCredentialError(str(payload.get("error_description") or payload.get("error") or "device authorization failed"), "server")
    return key, payload


def wait_for_approval(
    api_url: str,
    key: DpopKey,
    authorization: dict,
    store: CredentialStore,
    *,
    client: Optional[httpx.Client] = None,
    sleep=time.sleep,
) -> StoredCredential:
    """Poll until the accountable owner decides, then store the credential."""
    probe = RuntimeTokenProvider(
        api_url,
        InMemoryKeyOnlyStore(key),
        client=client,
    )
    interval = max(1, int(authorization.get("interval") or 5))
    deadline = time.time() + float(authorization.get("expires_in") or 600) + 30
    while time.time() < deadline:
        try:
            tokens = probe.token_request(
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": authorization["device_code"],
                    "client_id": CLIENT_ID,
                    "resource": "api",
                }
            )
        except RuntimeCredentialError as error:
            if error.kind in ("pending", "slow_down"):
                interval = error.interval or (interval + 5 if error.kind == "slow_down" else interval)
                sleep(interval)
                continue
            raise
        credential = StoredCredential(
            enrollment_id=tokens.get("enrollment_id") or authorization.get("enrollment_id", ""),
            agent_id=tokens.get("agent_id", ""),
            refresh_token=tokens["refresh_token"],
            private_key_pem=key.to_pem(),
            approval_expires_at=tokens.get("approval_expires_at"),
        )
        store.save(credential)
        return credential
    raise RuntimeCredentialError("The approval request expired.", "expired")


class InMemoryKeyOnlyStore(CredentialStore):
    """A store that carries only the key, for calls made before enrollment."""

    def __init__(self, key: DpopKey):
        self._credential = StoredCredential("", "", "", key.to_pem())

    def load(self):
        return self._credential

    def save(self, credential):  # pragma: no cover - never persisted
        self._credential = credential


def exchange_workload_token(
    api_url: str,
    subject_token: str,
    key: DpopKey,
    *,
    resource: str = "api",
    client: Optional[httpx.Client] = None,
) -> dict:
    """RFC 8693: this platform's OIDC token becomes a Contro1 access token.

    Which Agent it becomes is decided by a trust policy the accountable owner
    approved, never by anything this process asserts. No refresh token is
    issued: exchange again when the access token expires.
    """
    provider = RuntimeTokenProvider(api_url, InMemoryKeyOnlyStore(key), client=client)
    return provider.token_request(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": subject_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "client_id": CLIENT_ID,
            "resource": resource,
        }
    )
