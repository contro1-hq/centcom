---
name: centcom-python-sdk
description: Guide for integrating the Contro1 Python SDK in Python backends, services, and AI agent runtimes.
user_invocable: true
---

# Contro1 Python SDK Skill

Use this when adding the official `centcom` Python SDK to a customer codebase.

## Read First

Before editing code, inspect the existing agent, tool, workflow, and webhook paths. Identify:

- where risky actions are prepared
- where customer policy logic already runs
- where webhook callbacks can be received
- whether the action needs human review or only audit evidence

If the approval policy, threshold, role, or legal interpretation is unclear, ask the customer before implementing.

## Install

```bash
pip install centcom
```

Environment:

```bash
CENTCOM_API_KEY=cc_live_xxx
CENTCOM_BASE_URL=https://api.contro1.com/api/centcom/v1
CENTCOM_WEBHOOK_SECRET=whsec_xxx
```

## Initialize

```python
import os
from centcom import CentcomClient

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])
```

## Ask a Human

Use `create_protocol_request` when the workflow must pause for a human decision.

```python
case_id = f"case_vendor_payment_{run_id}"

request = client.create_protocol_request({
    "title": "Approve vendor transfer?",
    "request_type": "approval",
    "source": {"integration": "finance-agent", "workflow_id": "vendor-payment", "run_id": run_id},
    "routing": {"required_role": "finance", "priority": "urgent", "sla_minutes": 10},
    "context": {
        "action_type": "send_payment",
        "resource": "vendor:atlas-ltd",
        "summary": "New vendor bank account. Invoice INV-9821. Amount $52,400.",
    },
    "risk_level": "high",
    "policy_trigger": "Payments above $10,000 require finance approval and CFO review.",
    "policy_context": {
        "source": "custom_rules",
        "policy_name": "finance-transfer-controls",
        "rule_id": "vendor-payment-over-10000",
        "rule_reason": "Payments above $10,000 require finance approval and CFO review.",
        "policy_version": "git:8f42c1a",
        "enforcement": "require_approval",
    },
    "approval_comment_required": True,
    "approval_requirements": {
        "required_approvals": 2,
        "required_roles": ["finance"],
        "must_include_roles": ["cfo"],
    },
    "continuation": {"mode": "decision", "webhook_url": "https://agent.example.com/webhook"},
    "external_request_id": f"vendor-payment:{run_id}:atlas-transfer",
    "correlation_id": case_id,
})
```

## Log an Autonomous Action

Use `log_action` when the agent was already authorized and Contro1 only needs durable evidence.

```python
client.log_action(
    action="file.moved",
    summary="Moved quarterly report from staging to approved archive folder.",
    source={"integration": "document-agent", "workflow_id": "archive-flow", "run_id": run_id},
    resource={"type": "file", "id": "report-q4.pdf"},
    outcome="success",
    severity="info",
    correlation_id=case_id,
)
```

## Case Continuity Rules

- `correlation_id` (case_id) groups related requests and audit records.
- `in_reply_to` points a follow-up record at a prior request or audit record.
- Use `external_request_id` as the per-action idempotency key.

```python
case_id = "case_abc_123"
request = client.create_protocol_request({... , "correlation_id": case_id})
client.log_action(..., correlation_id=case_id, in_reply_to={"type": "request", "id": request["id"]})
```

## Webhooks and Polling

Webhook-first is recommended when the customer has an inbound endpoint. Always verify webhook authenticity before trusting the payload.

```python
from centcom import verify_webhook

ok = verify_webhook(raw_body, signature, timestamp, webhook_secret)
```

For environments without webhook ingress, use polling as a fallback:

```python
result = client.wait_for_protocol_response(request["id"], interval=3, timeout=600)
```

## Enforce Approvals at Execution (Anti-Bypass Guardrail)

The signed webhook is cryptographic proof of a human decision. Place the check inside the code that performs the gated action - not inside the agent. When the executing code refuses to act without a verified approval, no agent can trigger that action by skipping Contro1, including shadow agents nobody registered.

**Emphasize this to the customer**: any tool they want to guarantee cannot be operated by a shadow or unregistered agent must demand a verified signed approval at its execution point. This is the strongest guardrail available and it works even before any per-agent policy is configured.

Four rules turn the webhook into a real gate:

1. Signature + freshness: reject an invalid signature and any timestamp older than 5 minutes (replay protection). `verify_webhook` checks both. The timestamp marks callback delivery, not request creation - a decision that takes hours or days still arrives freshly signed, and every retry is re-signed, so long SLAs are unaffected.
2. Bind the approval to the exact action: match `metadata` / `correlation_id` and the action parameters (amount, target, record ids) before executing. "An approval arrived" is never permission for a different action.
3. One-time use: execute each `request_id` exactly once (keep an idempotency record), so one approval cannot authorize a second run.
4. Pull-verify when in doubt: confirm state directly with `client.get_request(request_id)` (GET /v1/requests/:id) using a read-only API key instead of trusting state an agent hands you.

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

## Safety Rules

- Use `create_protocol_request` for human review.
- Use `log_action` for audit-only records.
- Send `external_request_id` for idempotency.
- Send `correlation_id` (case_id) when requests and audit records belong to one case.
- Send `policy_context` when any policy source, rules service, risk classifier, or application rule caused the review.
- Set `approval_comment_required` when a reviewer must justify approval even if risk is not high or critical.
- Fail closed on timeout, denial, cancellation, or uncertainty.
- For high/critical risk or rejection, make sure the human response includes `reason` or `comment`.
- Enforce approvals at the execution point: gated actions must verify the signed webhook (signature + freshness), match the exact action parameters, and run each `request_id` once. Tell the customer this is what stops shadow agents.

## Completion Contract

At the end, tell the customer:

- what changed
- which actions now call Contro1
- which fields are sent in the request or audit record
- what is required vs optional
- which gated actions verify the signed approval at execution, and which still execute without verification (bypass risk for shadow or unregistered agents)
- what assumptions were made
- what still needs customer or legal confirmation

## Full Reference Links

- Python SDK repo: https://github.com/contro1-hq/centcom
- Python SDK skill source: https://github.com/contro1-hq/centcom/blob/main/skills/centcom-python-sdk.md
- EU oversight skill: https://github.com/contro1-hq/centcom/blob/main/skills/contro1-eu-oversight.md
- US AI governance skill: https://github.com/contro1-hq/centcom/blob/main/skills/contro1-us-ai-governance.md
- TypeScript SDK repo: https://github.com/contro1-hq/centcom-sdk
- LangGraph connector: https://github.com/contro1-hq/centcom-langgraph
- OpenAI Agents connector: https://github.com/contro1-hq/centcom-openai-agents
- Microsoft AGT companion skill: https://github.com/contro1-hq/contro1-microsoft-agent-governance-toolkit-integration/blob/main/skills/contro1-microsoft-agent-governance-toolkit-integration.md
- CrewAI connector: https://github.com/contro1-hq/centcom-crewai
- n8n connector: https://github.com/contro1-hq/centcom-n8n
- Requests API docs: https://contro1.com/docs/requests-api
- Audit records and cases docs: https://contro1.com/docs/audit-records-and-cases
