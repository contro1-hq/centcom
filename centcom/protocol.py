"""Contro1 Integration Protocol v1 types and adapters."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

CONTRO1_REQUEST_TYPES = ("approval", "input", "decision", "review")
CONTRO1_CONTINUATION_MODES = ("decision", "instruction")
CONTRO1_PRIORITIES = ("low", "normal", "high", "urgent")
CONTRO1_RISK_LEVELS = ("low", "medium", "high", "critical")
CONTRO1_STATUSES = ("approved", "denied", "cancelled", "timed_out", "provided_input", "resolved")

Contro1RequestType = Literal["approval", "input", "decision", "review"]
Contro1ContinuationMode = Literal["decision", "instruction"]
Contro1Priority = Literal["low", "normal", "high", "urgent"]
Contro1RiskLevel = Literal["low", "medium", "high", "critical"]
Contro1Status = Literal["approved", "denied", "cancelled", "timed_out", "provided_input", "resolved"]


class Contro1Source(TypedDict, total=False):
    integration: str
    framework: str
    workflow_id: str
    run_id: str
    session_id: str


class Contro1Routing(TypedDict, total=False):
    department: str
    required_role: str
    priority: Contro1Priority
    sla_minutes: int


class Contro1Actor(TypedDict, total=False):
    user_id: str
    user_email: str
    agent_id: str
    agent_name: str


class Contro1Context(TypedDict, total=False):
    tool_name: str
    tool_input: Any
    action_type: str
    resource: str
    environment: str
    summary: str
    action: dict[str, Any]
    machine_observed: dict[str, Any]
    agent_reported: dict[str, Any]


class Contro1Continuation(TypedDict, total=False):
    mode: Contro1ContinuationMode
    callback_url: str
    webhook_url: str
    resume_token: str
    expires_at: str


class ApprovalPolicy(TypedDict, total=False):
    mode: Literal["single", "all_of", "any_of", "threshold"]
    required_approvals: int
    required_roles: list[str]
    required_department_ids: list[str]
    separation_of_duties: bool
    fail_closed_on_timeout: bool


class ApprovalRequirements(TypedDict, total=False):
    required_approvals: int
    required_roles: list[str]
    must_include_roles: list[str]


class PolicyContext(TypedDict, total=False):
    source: str
    policy_name: str
    rule_id: str
    rule_reason: str
    policy_version: str
    enforcement: str


class DecisionContext(TypedDict, total=False):
    risk_level: Contro1RiskLevel
    policy_trigger: str
    policy_context: PolicyContext
    approval_comment_required: bool
    approval_requirements: ApprovalRequirements


class Contro1Request(TypedDict, total=False):
    id: str
    title: str
    description: str
    request_type: Contro1RequestType
    correlation_id: str
    external_request_id: str
    thread_id: str
    in_reply_to: dict[str, str]
    trace_id: str
    parent_trace_id: str
    tool_calls: list[dict[str, Any]]
    sub_agents: list[dict[str, Any]]
    retrieved_context: list[dict[str, Any]]
    source: Contro1Source
    routing: Contro1Routing
    actor: Contro1Actor
    context: Contro1Context
    continuation: Contro1Continuation
    approval_policy: ApprovalPolicy
    risk_level: Contro1RiskLevel
    policy_trigger: str
    policy_context: PolicyContext
    approval_comment_required: bool
    approval_requirements: ApprovalRequirements
    decision_context: DecisionContext
    metadata: dict[str, Any]


class Contro1Operator(TypedDict, total=False):
    id: str
    name: str
    department: str


class Contro1Response(TypedDict, total=False):
    request_id: str
    status: Contro1Status
    operator: Contro1Operator
    message: str
    structured_response: dict[str, Any]
    decision_type: Literal["approve", "reject", "respond"]
    resolved_at: str


def _build_context_text(request: Contro1Request) -> str:
    parts: list[str] = []
    description = request.get("description")
    if isinstance(description, str) and description.strip():
        parts.append(description.strip())

    context = request.get("context") or {}
    if isinstance(context, dict):
        for label, key in (
            ("Summary", "summary"),
            ("Tool", "tool_name"),
            ("Action", "action_type"),
            ("Resource", "resource"),
            ("Environment", "environment"),
        ):
            value = context.get(key)
            if isinstance(value, str) and value:
                parts.append(f"{label}: {value}")
        if "tool_input" in context:
            parts.append(f"Tool input: {json.dumps(context['tool_input'], ensure_ascii=True)}")

    title = request.get("title", "")
    fallback = title if isinstance(title, str) and title.strip() else "Contro1 request"
    return "\n".join(parts).strip() or fallback


def _map_request_type(request_type: str) -> str:
    if request_type == "input":
        return "free_text"
    if request_type == "decision":
        return "yes_no"
    return "approval"


def _map_priority(priority: str | None) -> str:
    return "urgent" if priority in {"high", "urgent"} else "normal"


def _extract_message(response: dict[str, Any] | None) -> str | None:
    if not isinstance(response, dict):
        return None
    for key in ("message", "comment", "reason", "value"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _infer_status(legacy_request: dict[str, Any]) -> Contro1Status:
    state = str(legacy_request.get("state", ""))
    if state == "cancelled":
        return "cancelled"
    if state == "expired":
        return "timed_out"

    response = legacy_request.get("response")
    if isinstance(response, dict):
        approved = response.get("approved")
        if isinstance(approved, bool):
            return "approved" if approved else "denied"
        value = response.get("value")
        if isinstance(value, bool):
            return "approved" if value else "denied"

    if state == "answered":
        return "provided_input" if legacy_request.get("type") == "free_text" else "resolved"
    return "timed_out"


def validate_contro1_request(request: Contro1Request) -> list[str]:
    errors: list[str] = []

    title = request.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("title is required")

    request_type = request.get("request_type")
    if request_type not in CONTRO1_REQUEST_TYPES:
        errors.append(f"request_type must be one of: {', '.join(CONTRO1_REQUEST_TYPES)}")

    source = request.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("integration"), str) or not source.get("integration", "").strip():
        errors.append("source.integration is required")

    continuation = request.get("continuation")
    mode = continuation.get("mode") if isinstance(continuation, dict) else None
    if mode not in CONTRO1_CONTINUATION_MODES:
        errors.append(f"continuation.mode must be one of: {', '.join(CONTRO1_CONTINUATION_MODES)}")

    routing = request.get("routing")
    if isinstance(routing, dict):
        priority = routing.get("priority")
        if priority is not None and priority not in CONTRO1_PRIORITIES:
            errors.append(f"routing.priority must be one of: {', '.join(CONTRO1_PRIORITIES)}")
        sla_minutes = routing.get("sla_minutes")
        if sla_minutes is not None and (not isinstance(sla_minutes, int) or sla_minutes <= 0):
            errors.append("routing.sla_minutes must be a positive integer")

    risk_level = request.get("risk_level")
    if risk_level is not None and risk_level not in CONTRO1_RISK_LEVELS:
        errors.append(f"risk_level must be one of: {', '.join(CONTRO1_RISK_LEVELS)}")

    policy_trigger = request.get("policy_trigger")
    if policy_trigger is not None and (not isinstance(policy_trigger, str) or not policy_trigger.strip()):
        errors.append("policy_trigger must be non-empty when provided")

    policy_context = request.get("policy_context")
    if policy_context is not None:
        if not isinstance(policy_context, dict):
            errors.append("policy_context must be an object when provided")
        elif not any(isinstance(value, str) and value.strip() for value in policy_context.values()):
            errors.append("policy_context must contain at least one non-empty field")

    approval_comment_required = request.get("approval_comment_required")
    if approval_comment_required is not None and not isinstance(approval_comment_required, bool):
        errors.append("approval_comment_required must be a boolean when provided")

    thread_id = request.get("thread_id")
    if isinstance(thread_id, str) and thread_id and not re.match(r"^thr_[A-Za-z0-9_-]{1,64}$", thread_id):
        errors.append("thread_id must match thr_[A-Za-z0-9_-]{1,64}")

    trace_id = request.get("trace_id")
    if isinstance(trace_id, str) and trace_id and not re.match(r"^trc_[A-Za-z0-9_-]{1,64}$", trace_id):
        errors.append("trace_id must match trc_[A-Za-z0-9_-]{1,64}")

    parent_trace_id = request.get("parent_trace_id")
    if isinstance(parent_trace_id, str) and parent_trace_id and not re.match(r"^trc_[A-Za-z0-9_-]{1,64}$", parent_trace_id):
        errors.append("parent_trace_id must match trc_[A-Za-z0-9_-]{1,64}")

    return errors


def validate_contro1_response(response: Contro1Response) -> list[str]:
    errors: list[str] = []
    request_id = response.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        errors.append("request_id is required")
    status = response.get("status")
    if status not in CONTRO1_STATUSES:
        errors.append(f"status must be one of: {', '.join(CONTRO1_STATUSES)}")
    resolved_at = response.get("resolved_at")
    if not isinstance(resolved_at, str) or not resolved_at.strip():
        errors.append("resolved_at is required")
    return errors


def to_legacy_create_request_params(request: Contro1Request) -> tuple[dict[str, Any], str | None]:
    metadata = dict(request.get("metadata") or {})
    metadata.update(
        {
            "protocol_version": "integration-v1",
            "request_type": request.get("request_type"),
            "source": request.get("source"),
            "routing": request.get("routing"),
            "actor": request.get("actor"),
            "context": request.get("context"),
            "continuation": request.get("continuation"),
        }
    )

    decision_context = dict(request.get("decision_context") or {})
    risk_level = request.get("risk_level")
    policy_trigger = request.get("policy_trigger")
    policy_context = request.get("policy_context")
    approval_comment_required = request.get("approval_comment_required")
    approval_requirements = request.get("approval_requirements")
    if risk_level:
        decision_context["risk_level"] = risk_level
        metadata["risk_level"] = risk_level
    if policy_trigger:
        decision_context["policy_trigger"] = policy_trigger
        metadata["policy_trigger"] = policy_trigger
    if policy_context:
        decision_context["policy_context"] = policy_context
        metadata["policy_context"] = policy_context
    if approval_comment_required is not None:
        decision_context["approval_comment_required"] = approval_comment_required
        metadata["approval_comment_required"] = approval_comment_required
    if approval_requirements:
        decision_context["approval_requirements"] = approval_requirements
        metadata["approval_requirements"] = approval_requirements
    if decision_context:
        metadata["decision_context"] = decision_context

    correlation_id = request.get("correlation_id")
    external_request_id = request.get("external_request_id")
    if isinstance(correlation_id, str) and correlation_id:
        metadata["correlation_id"] = correlation_id
    if isinstance(external_request_id, str) and external_request_id:
        metadata["external_request_id"] = external_request_id

    thread_id = request.get("thread_id")
    in_reply_to = request.get("in_reply_to")
    if isinstance(thread_id, str) and thread_id:
        metadata["thread_id"] = thread_id
    if isinstance(in_reply_to, dict):
        metadata["in_reply_to"] = in_reply_to
    tool_calls = request.get("tool_calls")
    sub_agents = request.get("sub_agents")
    retrieved_context = request.get("retrieved_context")
    if isinstance(tool_calls, list) and tool_calls:
        metadata["tool_calls"] = tool_calls
    if isinstance(sub_agents, list) and sub_agents:
        metadata["sub_agents"] = sub_agents
    if isinstance(retrieved_context, list) and retrieved_context:
        metadata["retrieved_context"] = retrieved_context

    request_type = str(request.get("request_type", "approval"))
    routing = request.get("routing") or {}
    continuation = request.get("continuation") or {}

    body: dict[str, Any] = {
        "type": _map_request_type(request_type),
        "question": request["title"],
        "context": _build_context_text(request),
        "priority": _map_priority(routing.get("priority") if isinstance(routing, dict) else None),
        "metadata": metadata,
    }

    if isinstance(continuation, dict):
        callback_url = continuation.get("callback_url") or continuation.get("webhook_url")
        if isinstance(callback_url, str) and callback_url:
            body["callback_url"] = callback_url

    if isinstance(routing, dict):
        required_role = routing.get("required_role")
        if isinstance(required_role, str) and required_role:
            body["required_role"] = required_role
        sla_minutes = routing.get("sla_minutes")
        if isinstance(sla_minutes, int) and sla_minutes > 0:
            body["sla_minutes"] = sla_minutes

    approval_policy = request.get("approval_policy")
    if isinstance(approval_policy, dict):
        body["approval_policy"] = approval_policy
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
    if isinstance(thread_id, str) and thread_id:
        body["thread_id"] = thread_id
    if isinstance(in_reply_to, dict):
        body["in_reply_to"] = in_reply_to
    trace_id = request.get("trace_id")
    parent_trace_id = request.get("parent_trace_id")
    if isinstance(trace_id, str) and trace_id:
        body["trace_id"] = trace_id
    if isinstance(parent_trace_id, str) and parent_trace_id:
        body["parent_trace_id"] = parent_trace_id
    if isinstance(tool_calls, list) and tool_calls:
        body["tool_calls"] = tool_calls
    if isinstance(sub_agents, list) and sub_agents:
        body["sub_agents"] = sub_agents
    if isinstance(retrieved_context, list) and retrieved_context:
        body["retrieved_context"] = retrieved_context

    source = request.get("source") or {}
    idempotency_key = external_request_id or correlation_id
    if not idempotency_key and isinstance(source, dict):
        run_id = source.get("run_id")
        if isinstance(run_id, str) and run_id:
            idempotency_key = run_id

    return body, idempotency_key


def from_legacy_request(legacy_request: dict[str, Any]) -> Contro1Response:
    response = legacy_request.get("response")
    metadata = legacy_request.get("metadata") or {}
    operator = None

    if isinstance(response, dict):
        operator_obj = response.get("operator")
        if isinstance(operator_obj, dict):
            operator = {
                "id": operator_obj.get("id"),
                "name": operator_obj.get("name"),
                "department": operator_obj.get("department"),
            }

    if operator is None and isinstance(metadata, dict):
        operator_obj = metadata.get("operator")
        if isinstance(operator_obj, dict):
            operator = {
                "id": operator_obj.get("id"),
                "name": operator_obj.get("name"),
                "department": operator_obj.get("department"),
            }

    responded_by = legacy_request.get("responded_by")
    if operator is None and isinstance(responded_by, str) and responded_by:
        operator = {"name": responded_by}

    resolved_at = legacy_request.get("responded_at") or legacy_request.get("created_at")
    if not isinstance(resolved_at, str) or not resolved_at:
        resolved_at = datetime.now(timezone.utc).isoformat()

    structured_response = response if isinstance(response, dict) else None
    canonical_decision = structured_response.get("decision_type") if structured_response else None
    if canonical_decision in ("approve", "reject", "respond"):
        decision_type = canonical_decision
    elif legacy_request.get("type") == "approval" and structured_response and isinstance(structured_response.get("approved"), bool):
        decision_type = "approve" if structured_response["approved"] else "reject"
    elif structured_response:
        decision_type = "respond"
    else:
        decision_type = None

    result: Contro1Response = {
        "request_id": str(legacy_request.get("id", "")),
        "status": _infer_status(legacy_request),
        "operator": operator,
        "message": _extract_message(structured_response),
        "structured_response": structured_response,
        "resolved_at": resolved_at,
    }
    if decision_type is not None:
        result["decision_type"] = decision_type
    return result
