# centcom

Official CENTCOM Python SDK for human-in-the-loop approval requests and webhook verification.

For LangGraph integration, use the companion package:
[`centcom-langgraph`](https://github.com/contro1-hq/centcom-langgraph).

## Skill

This repo includes an integration skill:
- `skills/centcom-python-sdk.md`

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
)
print(req["id"])
```

## Quick Verify

```bash
python -c "import centcom; print('centcom installed')"
```

## Related Packages

- [`centcom-langgraph`](https://github.com/contro1-hq/centcom-langgraph) for LangGraph pause/resume workflows
- [`@contro1/sdk`](https://github.com/contro1-hq/centcom-sdk) for Node/TypeScript integrations
- [`@contro1/claude-code`](https://github.com/contro1-hq/centcom-claude-code) for Claude Code `PreToolUse` approvals
