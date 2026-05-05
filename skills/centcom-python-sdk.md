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
thread_id = client.new_thread_id()

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
    "approval_requirements": {
        "required_approvals": 2,
        "required_roles": ["finance"],
        "must_include_roles": ["cfo"],
    },
    "continuation": {"mode": "decision", "webhook_url": "https://agent.example.com/webhook"},
    "external_request_id": f"vendor-payment:{run_id}:atlas-transfer",
    "thread_id": thread_id,
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
    thread_id=thread_id,
)
```

## Thread Rules

- `thread_id` groups related requests and audit records.
- `in_reply_to` points a follow-up record at a prior request or audit record.
- Do not use `thread_id` as an idempotency key. Use `external_request_id` for idempotency.

```python
thread_id = client.new_thread_id()
request = client.create_protocol_request({... , "thread_id": thread_id})
client.log_action(..., thread_id=thread_id, in_reply_to={"type": "request", "id": request["id"]})
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

## Safety Rules

- Use `create_protocol_request` for human review.
- Use `log_action` for audit-only records.
- Send `external_request_id` for idempotency.
- Send `thread_id` when requests and audit records belong to one run/case.
- Fail closed on timeout, denial, cancellation, or uncertainty.
- For high/critical risk or rejection, make sure the human response includes `reason` or `comment`.

## Completion Contract

At the end, tell the customer:

- what changed
- which actions now call Contro1
- which fields are sent in the request or audit record
- what is required vs optional
- what assumptions were made
- what still needs customer or legal confirmation

## Full Reference Links

- Python SDK repo: https://github.com/contro1-hq/centcom
- Python SDK skill source: https://github.com/contro1-hq/centcom/blob/main/skills/centcom-python-sdk.md
- EU oversight skill: https://github.com/contro1-hq/centcom/blob/main/skills/contro1-eu-oversight.md
- TypeScript SDK repo: https://github.com/contro1-hq/centcom-sdk
- LangGraph connector: https://github.com/contro1-hq/centcom-langgraph
- OpenAI Agents connector: https://github.com/contro1-hq/centcom-openai-agents
- CrewAI connector: https://github.com/contro1-hq/centcom-crewai
- n8n connector: https://github.com/contro1-hq/centcom-n8n
- Requests API docs: https://contro1.com/docs/requests-api
- Audit records and threads docs: https://contro1.com/docs/audit-records-and-threads
