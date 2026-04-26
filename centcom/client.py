"""CENTCOM Python SDK - CentcomClient for creating and managing HITL requests."""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

DEFAULT_BASE_URL = "https://contro1.com/api/centcom/v1"
DEFAULT_TIMEOUT = 30.0

# States that indicate the request lifecycle is complete or has a response
TERMINAL_STATES = {
    "answered", "callback_pending", "callback_delivered",
    "callback_failed", "closed", "expired", "cancelled",
}


class CentcomError(Exception):
    """Raised when the CENTCOM API returns an error."""

    def __init__(self, message: str, status_code: int = 0, response: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class CentcomClient:
    """
    Synchronous client for the CENTCOM Human Approval API.

    Usage:
        client = CentcomClient(api_key="cc_test_xxxx")
        req = client.create_request(
            type="yes_no",
            context="Order #12345 from VIP customer",
            question="Approve this $2,500 order?",
            callback_url="https://my-agent.example.com/webhook",
        )
        print(req["id"], req["state"])
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        res = self._http.request(method, path, **kwargs)
        data = res.json()
        if res.status_code >= 400:
            raise CentcomError(
                message=data.get("message", f"HTTP {res.status_code}"),
                status_code=res.status_code,
                response=data,
            )
        return data

    def create_request(
        self,
        type: str,
        context: str,
        question: str,
        callback_url: str,
        priority: str = "normal",
        required_role: Optional[str] = None,
        approval_policy: Optional[dict] = None,
        response_schema: Optional[dict] = None,
        metadata: Optional[dict] = None,
        sla_minutes: Optional[int] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """
        Create a new human-in-the-loop request.

        Args:
            type: Interaction type - "yes_no", "free_text", or "approval"
            context: Background info displayed to the operator
            question: The question for the human operator
            callback_url: Webhook URL for HMAC-signed response delivery
            priority: "normal" (10 min SLA) or "urgent" (3 min SLA)
            required_role: Role tag required to answer (e.g. "manager")
            approval_policy: Optional quorum policy for multi-person approvals
            response_schema: Expected response structure for validation
            metadata: Arbitrary data returned in the callback
            sla_minutes: Override SLA timeout
            idempotency_key: Unique key to prevent duplicate requests

        Returns:
            dict with the created request data including 'id' and 'state'
        """
        body: dict[str, Any] = {
            "type": type,
            "context": context,
            "question": question,
            "callback_url": callback_url,
            "priority": priority,
        }
        if required_role:
            body["required_role"] = required_role
        if approval_policy:
            body["approval_policy"] = approval_policy
        if response_schema:
            body["response_schema"] = response_schema
        if metadata:
            body["metadata"] = metadata
        if sla_minutes is not None:
            body["sla_minutes"] = sla_minutes

        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        return self._request("POST", "/requests", json=body, headers=headers)

    def get_request(self, request_id: str) -> dict:
        """Get the current state of a request."""
        return self._request("GET", f"/requests/{request_id}")

    def cancel_request(self, request_id: str) -> dict:
        """Cancel a pending request (must not yet be answered)."""
        return self._request("DELETE", f"/requests/{request_id}")

    def wait_for_response(
        self,
        request_id: str,
        interval: float = 3.0,
        timeout: float = 600.0,
    ) -> dict:
        """
        Poll until the request reaches a terminal state.

        Args:
            request_id: The request to poll
            interval: Seconds between polls (default: 3)
            timeout: Total timeout in seconds (default: 600)

        Returns:
            The request dict once it has a response or is terminal

        Raises:
            TimeoutError: If timeout expires before a response
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            req = self.get_request(request_id)
            if req.get("state") in TERMINAL_STATES:
                return req
            time.sleep(interval)
        raise TimeoutError(f"Timeout waiting for response on request {request_id}")

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> "CentcomClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
