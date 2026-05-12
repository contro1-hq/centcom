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
from centcom import CentcomClient, verify_webhook

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])
req = client.create_request(
    type="approval",
    context="Order #123 refund request",
    question="Approve refund?",
    callback_url="https://your-app.com/centcom-webhook",
    risk_level="high",
    policy_trigger="Refunds above $1,000 require manager review.",
    approval_policy={
        "mode": "threshold",
        "required_approvals": 2,
        "required_roles": ["manager", "admin"],
        "separation_of_duties": True,
        "fail_closed_on_timeout": True,
    },
)
print(req["id"])
```

For high-risk actions, callbacks are sent only after quorum is met, a reviewer rejects, or the request times out. Partial approvals are audit events and do not resume the agent.

## Correlation and Routing

- `external_request_id` = one external action idempotency key.
- `case_id` (send as `correlation_id`) = broader business case that can contain multiple requests and audit records.
- `in_reply_to` = direct continuation of a prior request or audit record.
- `POST /api/centcom/v1/requests/control-map` previews role mapping, fallback reviewers, shift coverage, and policy satisfiability before request creation.

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
        self._control_map_cache = self.client.post("/api/centcom/v1/requests/control-map", json=payload)
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
- [`@contro1/sdk`](https://github.com/contro1-hq/centcom-sdk) for Node/TypeScript integrations
- [`@contro1/claude-code`](https://github.com/contro1-hq/centcom-claude-code) for Claude Code `PreToolUse` approvals

## Ask a human

```python
client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])
thread_id = client.new_thread_id()

request = client.create_protocol_request({
    "title": "Approve vendor transfer?",
    "request_type": "approval",
    "source": {"integration": "finance-agent"},
    "risk_level": "high",
    "policy_trigger": "Payments above $10,000 require finance approval.",
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
