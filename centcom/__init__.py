from .actions import (
    ACTION_TERMINAL_STATES,
    ActionResultUnavailable,
    ActionsApi,
    ActionTimeout,
    did_execute,
    needs_human_resolution,
)
from .client import CentcomClient
from .protocol import (
    CONTRO1_CONTINUATION_MODES,
    CONTRO1_PRIORITIES,
    CONTRO1_REQUEST_TYPES,
    CONTRO1_RISK_LEVELS,
    CONTRO1_STATUSES,
    from_legacy_request,
    to_legacy_create_request_params,
    validate_contro1_request,
    validate_contro1_response,
)
from .webhook import verify_webhook

# Runtime connections need the optional "cryptography" extra:
#   pip install "centcom[runtime]"
try:  # pragma: no cover - optional extra
    from .runtime.auth import RuntimeAuth, broker_transport
    from .runtime.dpop import DpopKey
    from .runtime.enrollment import exchange_workload_token, register_key_with_ticket, wait_for_approval
    from .runtime.token_provider import (
        FileCredentialStore,
        InMemoryCredentialStore,
        RuntimeCredentialError,
        RuntimeTokenProvider,
        StoredCredential,
    )

    _RUNTIME_EXPORTS = [
        "RuntimeAuth",
        "RuntimeTokenProvider",
        "RuntimeCredentialError",
        "StoredCredential",
        "InMemoryCredentialStore",
        "FileCredentialStore",
        "DpopKey",
        "broker_transport",
        "register_key_with_ticket",
        "wait_for_approval",
        "exchange_workload_token",
    ]
except ImportError:  # pragma: no cover - optional extra
    _RUNTIME_EXPORTS = []

__all__ = _RUNTIME_EXPORTS + [
    "CentcomClient",
    "ActionsApi",
    "ActionTimeout",
    "ActionResultUnavailable",
    "ACTION_TERMINAL_STATES",
    "needs_human_resolution",
    "did_execute",
    "verify_webhook",
    "CONTRO1_REQUEST_TYPES",
    "CONTRO1_CONTINUATION_MODES",
    "CONTRO1_PRIORITIES",
    "CONTRO1_RISK_LEVELS",
    "CONTRO1_STATUSES",
    "validate_contro1_request",
    "validate_contro1_response",
    "to_legacy_create_request_params",
    "from_legacy_request",
]
__version__ = "1.5.0"
