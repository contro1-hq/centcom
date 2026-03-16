"""CENTCOM webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import time


MAX_TIMESTAMP_AGE_SECONDS = 300  # 5 minutes


def verify_webhook(
    raw_body: str | bytes,
    signature: str,
    timestamp: str,
    secret: str,
) -> bool:
    """
    Verify an incoming CENTCOM webhook signature.

    Args:
        raw_body: The raw HTTP request body (string or bytes)
        signature: The X-CentCom-Signature header value (hex string)
        timestamp: The X-CentCom-Timestamp header value (unix seconds)
        secret: Your organization's webhook signing secret (whsec_xxx)

    Returns:
        True if the signature is valid and the timestamp is fresh
    """
    # Validate timestamp
    try:
        ts = int(timestamp)
    except (ValueError, TypeError):
        return False

    age = abs(int(time.time()) - ts)
    if age > MAX_TIMESTAMP_AGE_SECONDS:
        return False

    # Compute expected signature
    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8")

    payload = f"{timestamp}.{raw_body}"
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison
    return hmac.compare_digest(signature, expected)
