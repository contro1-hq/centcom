"""CENTCOM Python SDK - CentcomClient for creating and managing HITL requests."""

from __future__ import annotations

import time
import secrets
from typing import Any, Optional

import httpx
from .protocol import (
    Contro1Request,
    Contro1Response,
    from_legacy_request,
    to_legacy_create_request_params,
    validate_contro1_request,
)

DEFAULT_BASE_URL = "https://api.contro1.com/api/centcom/v1"
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

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        res = self._http.request(method, path, **kwargs)
        content_type = res.headers.get("content-type", "")
        data = res.json() if res.content and "application/json" in content_type else res.text
        if res.status_code >= 400:
            message = data.get("message", f"HTTP {res.status_code}") if isinstance(data, dict) else f"HTTP {res.status_code}"
            raise CentcomError(
                message=message,
                status_code=res.status_code,
                response=data if isinstance(data, dict) else {"body": data},
            )
        return data

    def request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Low-level request helper for new /v1 endpoints before a typed wrapper exists."""
        return self._request(method, path, **kwargs)

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        """GET a /v1 endpoint relative to the configured base URL."""
        return self._request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
        """POST to a /v1 endpoint relative to the configured base URL."""
        return self._request("POST", path, json=json, headers=headers)

    def delete(self, path: str, json: Optional[dict] = None, headers: Optional[dict] = None) -> dict:
        """DELETE a /v1 endpoint relative to the configured base URL."""
        return self._request("DELETE", path, json=json, headers=headers)

    def create_request(
        self,
        type: str,
        context: str,
        question: str,
        callback_url: Optional[str] = None,
        priority: str = "normal",
        required_role: Optional[str] = None,
        approval_policy: Optional[dict] = None,
        response_schema: Optional[dict] = None,
        metadata: Optional[dict] = None,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[dict] = None,
        trace_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        tool_calls: Optional[list[dict]] = None,
        sub_agents: Optional[list[dict]] = None,
        retrieved_context: Optional[list[dict]] = None,
        sla_minutes: Optional[int] = None,
        risk_level: Optional[str] = None,
        policy_trigger: Optional[str] = None,
        policy_context: Optional[dict] = None,
        approval_comment_required: Optional[bool] = None,
        approval_requirements: Optional[dict] = None,
        decision_context: Optional[dict] = None,
        external_request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """
        Create a new human-in-the-loop request.

        Args:
            type: Interaction type - "yes_no", "free_text", or "approval"
            context: Background info displayed to the operator
            question: The question for the human operator
            callback_url: Optional webhook URL for HMAC-signed response delivery
            priority: "normal" (10 min SLA) or "urgent" (3 min SLA)
            required_role: Role tag required to answer (e.g. "manager")
            approval_policy: Optional quorum policy for multi-person approvals
            response_schema: Expected response structure for validation
            metadata: Arbitrary data returned in the callback
            thread_id: Case/thread id used to group related requests and audit records
            in_reply_to: Direct reference to a prior request or audit record
            trace_id: Execution trace id (trc_...)
            parent_trace_id: Parent execution trace id
            tool_calls: Tool-call evidence captured before request creation
            sub_agents: Child/sub-agent evidence captured before request creation
            retrieved_context: Retrieval evidence captured before request creation
            sla_minutes: Override SLA timeout
            risk_level: Optional customer-assessed risk level: low, medium, high, or critical
            policy_trigger: Optional customer policy text explaining why oversight is required
            policy_context: Optional policy/risk evidence envelope from any policy source
            approval_comment_required: Require reviewer comment even when risk is not high/critical
            approval_requirements: Optional audit context for approval expectations
            decision_context: Optional full decision evidence envelope
            external_request_id: External action id, also accepted as an idempotency key
            correlation_id: Business case id used to group related events
            idempotency_key: Unique key to prevent duplicate requests

        Returns:
            dict with the created request data including 'id' and 'state'
        """
        body: dict[str, Any] = {
            "type": type,
            "context": context,
            "question": question,
            "priority": priority,
        }
        if callback_url:
            body["callback_url"] = callback_url
        if required_role:
            body["required_role"] = required_role
        if approval_policy:
            body["approval_policy"] = approval_policy
        if response_schema:
            body["response_schema"] = response_schema
        if metadata:
            body["metadata"] = metadata
        if thread_id:
            body["thread_id"] = thread_id
        if in_reply_to:
            body["in_reply_to"] = in_reply_to
        if trace_id:
            body["trace_id"] = trace_id
        if parent_trace_id:
            body["parent_trace_id"] = parent_trace_id
        if tool_calls:
            body["tool_calls"] = tool_calls
        if sub_agents:
            body["sub_agents"] = sub_agents
        if retrieved_context:
            body["retrieved_context"] = retrieved_context
        if sla_minutes is not None:
            body["sla_minutes"] = sla_minutes
        if risk_level:
            body["risk_level"] = risk_level
        if policy_trigger:
            body["policy_trigger"] = policy_trigger
        if policy_context:
            body["policy_context"] = policy_context
        if approval_comment_required is not None:
            body["approval_comment_required"] = approval_comment_required
        if approval_requirements:
            body["approval_requirements"] = approval_requirements
        if decision_context:
            body["decision_context"] = decision_context
        if external_request_id:
            body["external_request_id"] = external_request_id
        if correlation_id:
            body["correlation_id"] = correlation_id

        headers = {}
        dedupe_key = idempotency_key or external_request_id or correlation_id
        if dedupe_key:
            headers["Idempotency-Key"] = dedupe_key

        return self._request("POST", "/requests", json=body, headers=headers)

    def new_thread_id(self) -> str:
        """Generate a client-side thread id for related requests and audit records."""
        return f"thr_{secrets.token_hex(16)}"

    def log_action(
        self,
        action: str,
        summary: str,
        source: dict,
        actor: Optional[dict] = None,
        resource: Optional[dict] = None,
        outcome: str = "success",
        severity: str = "info",
        correlation_id: Optional[str] = None,
        external_request_id: Optional[str] = None,
        risk_level: Optional[str] = None,
        policy_trigger: Optional[str] = None,
        approval_requirements: Optional[dict] = None,
        decision_context: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
        occurred_at: Optional[str] = None,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[dict] = None,
        trace_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        tool_calls: Optional[list[dict]] = None,
    ) -> dict:
        """Record an autonomous agent action that does not require human review."""
        body: dict[str, Any] = {
            "action": action,
            "summary": summary,
            "source": source,
            "outcome": outcome,
            "severity": severity,
        }
        if actor:
            body["actor"] = actor
        if resource:
            body["resource"] = resource
        if correlation_id:
            body["correlation_id"] = correlation_id
        if external_request_id:
            body["external_request_id"] = external_request_id
        if risk_level:
            body["risk_level"] = risk_level
        if policy_trigger:
            body["policy_trigger"] = policy_trigger
        if approval_requirements:
            body["approval_requirements"] = approval_requirements
        if decision_context:
            body["decision_context"] = decision_context
        if tags:
            body["tags"] = tags
        if metadata:
            body["metadata"] = metadata
        if occurred_at:
            body["occurred_at"] = occurred_at
        if thread_id:
            body["thread_id"] = thread_id
        if in_reply_to:
            body["in_reply_to"] = in_reply_to
        if trace_id:
            body["trace_id"] = trace_id
        if parent_trace_id:
            body["parent_trace_id"] = parent_trace_id
        if tool_calls:
            body["tool_calls"] = tool_calls

        return self._request("POST", "/audit-records", json=body)

    def create_protocol_request(self, request: Contro1Request) -> dict:
        """Create a request using canonical Contro1 Integration Protocol v1 format."""
        errors = validate_contro1_request(request)
        if errors:
            raise ValueError(f"Invalid Contro1Request: {'; '.join(errors)}")

        body, idempotency_key = to_legacy_create_request_params(request)
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return self._request("POST", "/requests", json=body, headers=headers)

    def preview_control_map(self, params: dict) -> dict:
        """Preview role mapping, fallback routing, shift coverage, and policy satisfiability."""
        looks_protocol = any(key in params for key in ("request_type", "source", "continuation"))
        if looks_protocol:
            body, _idempotency_key = to_legacy_create_request_params(params)  # type: ignore[arg-type]
        else:
            body = dict(params)
        body.pop("idempotency_key", None)
        return self._request("POST", "/requests/control-map", json=body)

    def list_requests(
        self,
        thread_id: Optional[str] = None,
        state: Optional[str] = None,
        agent_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> dict:
        """List recent requests or all requests in a thread."""
        params = {
            "thread_id": thread_id,
            "state": state,
            "agent_id": agent_id,
            "limit": limit,
        }
        return self._request("GET", "/requests", params={k: v for k, v in params.items() if v is not None})

    def get_request(self, request_id: str) -> dict:
        """Get the current state of a request."""
        return self._request("GET", f"/requests/{request_id}")

    def get_protocol_response(self, request_id: str) -> Contro1Response:
        """Get a request and map it to canonical Contro1Response."""
        req = self.get_request(request_id)
        return from_legacy_request(req)

    def get_request_evidence(self, request_id: str) -> dict:
        """Export one request as a signed JSON evidence packet when signing is configured."""
        return self._request("GET", f"/requests/{request_id}/evidence")

    def list_audit_records(self, **filters: Any) -> dict:
        """List audit-only records with optional backend-supported filters."""
        return self._request("GET", "/audit-records", params={k: v for k, v in filters.items() if v is not None})

    def get_audit_record(self, record_id: str) -> dict:
        """Get one audit-only record."""
        return self._request("GET", f"/audit-records/{record_id}")

    def get_thread(self, thread_id: str) -> dict:
        """Read a mixed request/audit timeline by thread id."""
        return self._request("GET", f"/threads/{thread_id}")

    def get_trace(self, trace_id: str) -> dict:
        """Read an execution trace timeline by trace id."""
        return self._request("GET", f"/traces/{trace_id}")

    def register_agent(
        self,
        name: str,
        framework: Optional[str] = None,
        description: Optional[str] = None,
        owner: Optional[str] = None,
    ) -> dict:
        """Register or retrieve a claimed agent identity."""
        body = {
            "name": name,
            "framework": framework,
            "description": description,
            "owner": owner,
        }
        return self._request("POST", "/agents/register", json={k: v for k, v in body.items() if v is not None})

    def list_agents(
        self,
        framework: Optional[str] = None,
        verification_status: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        """List registered/claimed agents."""
        params = {
            "framework": framework,
            "verification_status": verification_status,
            "status": status,
        }
        return self._request("GET", "/agents", params={k: v for k, v in params.items() if v is not None})

    def get_agent(self, agent_id: str) -> dict:
        """Get one agent identity."""
        return self._request("GET", f"/agents/{agent_id}")

    def get_agent_trail(self, agent_id: str, trace_id: Optional[str] = None, limit: Optional[int] = None) -> dict:
        """Read an agent trail, optionally scoped to one trace."""
        params = {"trace_id": trace_id, "limit": limit}
        return self._request("GET", f"/agents/{agent_id}/trail", params={k: v for k, v in params.items() if v is not None})

    def get_agent_evidence(self, agent_id: str, limit: Optional[int] = None, format: Optional[str] = None) -> dict:
        """Export a signed evidence bundle for an agent."""
        params = {"limit": limit, "format": format}
        return self._request("GET", f"/agents/{agent_id}/evidence", params={k: v for k, v in params.items() if v is not None})

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

    def wait_for_protocol_response(
        self,
        request_id: str,
        interval: float = 3.0,
        timeout: float = 600.0,
    ) -> Contro1Response:
        """Poll and return canonical Contro1Response once terminal."""
        req = self.wait_for_response(request_id, interval=interval, timeout=timeout)
        return from_legacy_request(req)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> "CentcomClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
