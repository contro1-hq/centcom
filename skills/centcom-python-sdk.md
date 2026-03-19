---
name: centcom-python-sdk
description: Guide for integrating the CENTCOM Python SDK (request creation, webhook verification, and polling fallback).
user_invocable: true
---

# CENTCOM Python SDK Integration Guide

You are helping a developer integrate the `centcom` Python SDK into an existing backend service.

## Step 1: Understand Their Runtime

Read their backend entrypoints and identify:
- Where approval requests are created
- Where webhook endpoints are defined
- Whether they need webhook-first flow, polling fallback, or both

If unclear, ask which endpoint should receive CENTCOM callbacks.

## Step 2: Install and Configure

Install package:

```bash
pip install centcom
```

Set required environment variable:

```bash
CENTCOM_API_KEY=cc_live_xxx
```

Optional:
- `CENTCOM_BASE_URL` for non-default environments
- App-specific webhook secret storage

## Step 3: Create Requests

Use `CentcomClient`:

```python
from centcom import CentcomClient

client = CentcomClient(api_key=os.environ["CENTCOM_API_KEY"])

request = client.create_request(
    type="approval",
    question="Approve refund for order #123?",
    context="Customer requested full refund after shipment delay.",
    callback_url="https://your-app.com/centcom-webhook",
    priority="urgent",
    metadata={"source": "orders-service"},
)
```

For polling-only clients, `callback_url` can be omitted.

Mini example (role-gated request):
```python
request = client.create_request(
    type="approval",
    question="Approve infrastructure change?",
    context="Terraform plan affects production networking.",
    required_role="manager",
)
```

## Step 4: Handle Responses

Webhook-first (recommended when available):
- Receive signed webhook payload from CENTCOM
- Verify signature before trusting payload
- Correlate by `request_id` and metadata

Polling fallback:

```python
result = client.wait_for_response(request["id"], interval=3, timeout=600)
```

Use polling for environments without webhook ingress or for local debugging.

## Step 5: Verify Webhooks

Always validate webhook authenticity:

```python
from centcom import verify_webhook

ok = verify_webhook(raw_body, signature, timestamp, webhook_secret)
```

Reject invalid signatures with non-2xx status.

## Step 6: Add Reliability and Safety

- Generate idempotency keys for retried create calls.
- Store minimal metadata needed for correlation.
- Never log raw API keys or secrets.
- Keep timeout/error handling explicit around network calls.

## Common Patterns

### Approval Gate in Business Flow
Create request -> wait for decision -> continue only if approved.

### Async Worker + Webhook
Create request in API thread, finalize decision in webhook handler/worker.

### Polling in Tests
Use short polling interval and test API keys for deterministic integration tests.
