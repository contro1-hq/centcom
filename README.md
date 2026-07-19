# centcom

Official CENTCOM Python SDK for human-in-the-loop approval requests and webhook verification.

## Agent Integration Kit

To save time, give your coding agent this skill. It inspects your system, reports governance gaps, and suggests Contro1 integration (optional):

```
https://contro1.com/agent-kit
```

For LangGraph integration, use the companion package:
[`centcom-langgraph`](https://github.com/contro1-hq/centcom-langgraph).

## Skill

This repo includes an integration skill:
- `skills/centcom-python-sdk.md`
- `skills/contro1-eu-oversight.md`
- `skills/contro1-us-ai-governance.md`

## Connector Repositories

- [centcom-openai-agents](https://github.com/contro1-hq/centcom-openai-agents)
- [centcom-crewai](https://github.com/contro1-hq/centcom-crewai)
- [centcom-n8n](https://github.com/contro1-hq/centcom-n8n)

## Install

```bash
pip install centcom
```

## Quick Start

```python
import os
from centcom import CentcomClient

def issue_refund() -> None:
    ...  # Your business logic runs only after approval.

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])
agent = client.register_agent("Refund Agent", framework="custom-agent")["agent"]

req = client.create_protocol_request({
    "title": "Approve refund for order #123?",
    "request_type": "approval",
    "source": {"integration": "python-sdk"},
    "actor": {"agent_id": agent["agent_id"]},
    "context": {
        "action": {"tool": "issue_refund", "input": {"order_id": 123, "amount_usd": 1200}},
        "machine_observed": {"trigger": "Customer refund request"},
        "agent_reported": {"justification": "Shipping-failure exception"},
    },
    "continuation": {"mode": "decision"},
    "risk_level": "high",
    "policy_trigger": "Refunds above $1,000 require manager review",
})

decision = client.wait_for_protocol_response(req["request_id"])
if decision["decision_type"] == "approve":
    issue_refund()  # Resume only after the canonical human decision.
```

For callback-based agents, add `callback_url` inside the same `continuation` object and verify the signed webhook before resuming. Partial approvals are audit events and do not resume the agent.

## Send context the reviewer can trust

Build the request's `context` at the gate (the code that intercepts the tool call), from three sources: the exact tool input copied verbatim by your code, the user message or event that triggered the run, and the agent's own justification (make `reason` a required parameter of the risky tool so the model produces it at decision time, not after the fact).

Keep provenance separate inside `context`: a `machine_observed` block for facts your code observed, and an `agent_reported` block for text the model wrote. `agent_reported` text must never change routing, `risk_level`, or approval policy - it only informs the human, since a prompt-injected agent can write a very persuasive justification. If a high-risk request arrives without its required `machine_observed` context, fail closed instead of asking a human to guess.

```python
req = client.create_protocol_request({
    "title": "Approve $12,400 transfer to acct_889?",
    "request_type": "approval",
    "context": {
        "action": {"tool": "transfer_money", "input": {"to": "acct_889", "amount_usd": 12400}},
        "machine_observed": {
            "triggered_by": "Support ticket #5521: customer requests refund for order #1842",
            "recent_tool_calls": ["lookup_order", "check_refund_policy"],
        },
        "agent_reported": {
            "justification": "Refund qualifies under the shipping-failure exception policy.",
        },
    },
    "risk_level": "high",
})
```

See https://contro1.com/docs/requests-api for the full pattern.

## Enforce approvals at execution (anti-bypass guardrail)

The signed webhook is cryptographic proof of a human decision. Put the check inside the code that performs the action - not inside the agent. When the executing code refuses to act without a verified approval, no agent can trigger that action by skipping Contro1, including shadow agents nobody registered. Any tool that must never run without human sign-off (payments, deploys, data deletion) should demand a verified signed approval at its execution point.

Four rules turn the webhook into a real gate:

1. **Signature + freshness**: `verify_webhook` rejects invalid signatures and timestamps older than 5 minutes (replay protection). The timestamp marks callback delivery, not request creation - a decision that takes hours or days still arrives freshly signed, and every retry is re-signed, so long SLAs are unaffected.
2. **Bind the approval to the exact action**: match `metadata` / `correlation_id` and the action parameters (amount, target, record ids) before executing. "An approval arrived" is never permission for a different action.
3. **One-time use**: execute each `request_id` exactly once (keep an idempotency record).
4. **Pull-verify when in doubt**: confirm state directly with `client.get_request(request_id)` using a read-only API key instead of trusting state an agent hands you.

```python
from centcom import verify_webhook

# The execution gate lives in the service that performs the action - not in the agent.
@app.post("/webhooks/contro1")
async def contro1_webhook(request: Request):
    raw = await request.body()
    # 1. Signature + freshness: rejects forgeries and replayed approvals.
    #    The timestamp is the callback's SEND time, not the request's creation
    #    time - a decision that took days still verifies (retries are re-signed).
    if not verify_webhook(raw, request.headers["X-CentCom-Signature"],
                          request.headers["X-CentCom-Timestamp"], WEBHOOK_SECRET):
        raise HTTPException(401, "invalid signature")

    payload = json.loads(raw)
    if payload.get("status") != "approved":
        return {"ok": True}

    # 2. Bind the approval to the exact pending action and its parameters
    action = pending_actions.get(payload["metadata"]["case_id"])
    if not action or action.amount != payload["metadata"]["amount"]:
        alert_security("approval does not match a pending action", payload["request_id"])
        return {"ok": True}

    # 3. One-time use: a request_id executes exactly once
    if not executed.add_if_absent(payload["request_id"]):
        return {"ok": True}

    # 4. Only now perform the action
    perform_action(action)
    return {"ok": True}
```

## Correlation and Routing

- `external_request_id` = one external action idempotency key.
- `case_id` (send as `correlation_id`) = broader business case that can contain multiple requests and audit records.
- `in_reply_to` = direct continuation of a prior request or audit record.
- `POST /api/centcom/v1/requests/control-map` optionally previews role mapping, fallback reviewers, shift coverage, and policy satisfiability for complex routing.

## Policy evidence fields

Use these fields from any policy or risk source, not only a specific framework:

- `risk_level`: `low`, `medium`, `high`, or `critical`.
- `policy_trigger`: short human-readable reason review is required.
- `policy_context`: evidence envelope with `source`, `policy_name`, `rule_id`, `rule_reason`, `policy_version`, and `enforcement`.
- `approval_comment_required`: force reviewer justification even when risk is low or medium.
- `decision_comment_policy`: effective per-key snapshot returned as `optional`, `risk_based`, or `always`; a request can tighten it but cannot loosen it.

Keep these concepts separate: `policy_trigger` explains why automation paused; `context.agent_reported.justification` is the agent's unverified claim; an approval decision comment is written by the reviewer when policy requires it; a `free_text` response is the requested human input itself and is always non-empty.

Contro1 does not need to own your policy engine. Your app, rules service, Microsoft AGT, OPA, Cedar, or custom code can decide that review is required; Contro1 handles routing, human decision, signed callback, and audit evidence.

## Customer Agent Plugin Pattern

Build one small adapter in the customer orchestrator so agent prompts stay minimal and token-efficient:

```python
class Contro1Plugin:
    def __init__(self, client):
        self.client = client
        self._control_map_cache = None
        self._control_map_ts = 0

    def preview_policy(self, payload, ttl_sec=300):
        now = time.time()
        if self._control_map_cache and now - self._control_map_ts < ttl_sec:
            return self._control_map_cache
        self._control_map_cache = self.client.preview_control_map(payload)
        self._control_map_ts = now
        return self._control_map_cache

    def request_human_review(self, *, title, context, case_id, action_id, **kwargs):
        return self.client.create_protocol_request({
            "title": title,
            "context": context,
            "external_request_id": action_id,
            "correlation_id": case_id,
            **kwargs,
        })

    def log_audit_action(self, *, action, summary, case_id, in_reply_to=None, **kwargs):
        return self.client.log_action(
            action=action,
            summary=summary,
            correlation_id=case_id,
            in_reply_to=in_reply_to,
            **kwargs,
        )
```

## Quick Verify

```bash
python -c "import centcom; print('centcom installed')"
```

## Related Packages

- [`centcom-langgraph`](https://github.com/contro1-hq/centcom-langgraph) for LangGraph pause/resume workflows
- [`contro1-microsoft-agent-governance-toolkit-integration`](https://github.com/contro1-hq/contro1-microsoft-agent-governance-toolkit-integration) for Microsoft AGT `require_approval` policy decisions
- [`@contro1/sdk`](https://github.com/contro1-hq/centcom-sdk) for Node/TypeScript integrations
- [`@contro1/claude-code`](https://github.com/contro1-hq/centcom-claude-code) for selective production-deploy approvals at Claude Code's `PermissionRequest` boundary

## Ask a human

```python
client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])
thread_id = client.new_thread_id()

request = client.create_protocol_request({
    "title": "Approve vendor transfer?",
    "description": "Payment run 1024 wants to transfer funds to a vendor.",
    "request_type": "approval",
    "source": {"integration": "finance-agent"},
    "risk_level": "high",
    "policy_trigger": "Payments above $10,000 require finance approval.",
    "policy_context": {
        "source": "custom_rules",
        "policy_name": "finance-transfer-controls",
        "rule_id": "payment-over-10000",
        "rule_reason": "Payments above $10,000 require finance approval.",
        "policy_version": "git:8f42c1a",
        "enforcement": "require_approval",
    },
    "approval_comment_required": True,
    "continuation": {"mode": "decision", "callback_url": "https://agent.example.com/webhook"},
    "external_request_id": "payment:run_1024:approve",
    "correlation_id": "case_payment_run_1024",
})
```

## Log an autonomous action

```python
client.log_action(
    action="transfer.executed",
    summary="Transferred $500 to approved vendor account",
    source={"integration": "finance-agent"},
    outcome="success",
    correlation_id="case_payment_run_1024",
    in_reply_to={"type": "request", "id": request["id"]},
)
```

Use the same API key and base URL for both calls.

## API

- `request(method, path, **kwargs)`, `get(path, params=None)`, `post(path, json=None)`, `delete(path, json=None)`
- `create_request(...)`, `create_protocol_request(request)`, `log_action(...)`
- `preview_control_map(params)`, `list_requests(...)`, `get_request(request_id)`
- `get_protocol_response(request_id)`, `wait_for_response(...)`, `wait_for_protocol_response(...)`
- `get_request_evidence(request_id)`, `get_thread(thread_id)`, `get_trace(trace_id)`
- `register_agent(...)`, `list_agents(...)`, `get_agent(...)`, `get_agent_trail(...)`, `get_agent_evidence(...)`
