# centcom

Official CENTCOM Python SDK for human-in-the-loop approval requests and webhook verification.

## Install

```bash
pip install centcom
```

## Quick Start

```python
from centcom import CentcomClient, verify_webhook

client = CentcomClient(api_key="cc_live_xxx")
req = client.create_request(
    type="approval",
    context="Order #123 refund request",
    question="Approve refund?",
    callback_url="https://your-app.com/centcom-webhook",
)
print(req["id"])
```
