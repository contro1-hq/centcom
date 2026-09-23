"""Action Gateway client.

The rest of this SDK asks a human a question and reads the answer. This part
makes Contro1 DO something with a customer's credential, so three of its design
choices are deliberately less convenient than they could be.

1. An idempotency key is REQUIRED for anything side-effecting, and this module
   will not invent one. A key derived from the payload would collapse two
   legitimate identical reminders an hour apart into a single send. Only the
   caller knows whether two identical requests are one intent or two.

2. Waiting is not retrying. ``wait_for_invocation`` polls a state and never
   re-submits. An SDK that retried a send on a network blip would send twice,
   and the caller would have no way to find out.

3. ``execution_indeterminate`` is RETURNED, not raised. It means the provider
   call may or may not have taken effect. Raising it invites a retry, which is
   exactly the wrong move; it is a state a person has to resolve.
"""

from __future__ import annotations

import time
from typing import Any, Optional

ACTION_TERMINAL_STATES = (
    "executed",
    "execution_failed",
    "execution_indeterminate",
    "denied",
    "expired",
    "cancelled",
    "binding_mismatch",
)

AUTHORITY_MODES = ("agent_principal", "user_delegated")
ACTION_ACCOUNT_MODES = ("personal", "shared", "organization")


class ActionTimeout(Exception):
    """Raised when an invocation has not reached a terminal state in time.

    Deliberately its own type rather than a generic error: the invocation is
    STILL LIVE on the server when this is raised, and the correct response is to
    read it again later, never to submit a second one.
    """

    def __init__(self, invocation_id: str, state: str):
        self.invocation_id = invocation_id
        self.state = state
        super().__init__(
            f"Timed out waiting for invocation {invocation_id}; it is still in state "
            f'"{state}" and may still execute. Re-read it rather than resubmitting.'
        )


class ActionResultUnavailable(Exception):
    """The invocation has no result to read, and the message says why.

    Not a failure of the Action: an expired or unreadable result belongs to an
    Action that ran and succeeded. Do not resubmit to get it back.
    """

    def __init__(self, invocation_id: str, reason: str):
        self.invocation_id = invocation_id
        self.reason = reason
        super().__init__(f"No result for invocation {invocation_id}: {reason}")


class ActionsApi:
    """Attached to a :class:`CentcomClient` as ``client.actions``."""

    def __init__(self, client: Any):
        self._client = client

    def invoke(
        self,
        action_id: str,
        input: dict,
        authority_mode: str,
        account_mode: str,
        *,
        action_version: Optional[int] = None,
        connection_id: Optional[str] = None,
        acting_user_id: Optional[str] = None,
        target_resource: Optional[dict] = None,
        trace_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        callback_url: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Submit an Action.

        Returns as soon as the Gateway accepts it, which may be before anything
        has run: an Action needing approval sits in ``awaiting_approval`` until
        a human decides.

        ``authority_mode``
            ``agent_principal`` - the agent acts as itself, with no acting user.
            ``user_delegated`` - the call is made for a person named in
            ``acting_user_id``. Accepted from that person's own credential, or
            from an agent the person delegated this Action to (``whoami`` lists
            them under ``acts_for``). A personal account always needs this.

        ``idempotency_key``
            Required for a side-effecting Action. Not generated here: a key
            derived from the payload would merge two legitimate identical sends.
        """
        if authority_mode not in AUTHORITY_MODES:
            raise ValueError(f"authority_mode must be one of {AUTHORITY_MODES}")
        if account_mode not in ACTION_ACCOUNT_MODES:
            raise ValueError(f"account_mode must be one of {ACTION_ACCOUNT_MODES}")

        body: dict = {
            "action_id": action_id,
            "input": input,
            "authority_mode": authority_mode,
            "account_mode": account_mode,
        }
        optional = {
            "action_version": action_version,
            "connection_id": connection_id,
            "acting_user_id": acting_user_id,
            "target_resource": target_resource,
            "trace_id": trace_id,
            "parent_trace_id": parent_trace_id,
            "thread_id": thread_id,
            "callback_url": callback_url,
        }
        # Omitted rather than sent as null: the ingress rejects unknown and
        # malformed fields, and a null is not the same as absent to it.
        body.update({key: value for key, value in optional.items() if value is not None})

        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._client.post("/actions/invoke", json=body, headers=headers)

    def delegate(
        self,
        agent_id: str,
        child_agent_id: str,
        max_risk_level: str,
        allowed_action_ids: list | None = None,
        allowed_connection_ids: list | None = None,
        ttl_seconds: int | None = None,
    ) -> dict:
        """Mint a delegation token for a child agent.

        The parent is whoever this client is authenticated AS; ``agent_id`` is
        checked against the credential rather than trusted from it. The Gateway
        resolves the caller's authority at this moment and refuses anything
        wider, so authority removed a minute ago cannot be delegated now.

        ``max_risk_level`` is required, not inherited. A delegation that
        silently took its parent's ceiling would be the widest one available,
        chosen by omission.

        The returned ``token`` is shown once. Hand it to the child process and
        let it expire; nothing stores it and no endpoint can read it back.
        """
        body = {
            "child_agent_id": child_agent_id,
            "max_risk_level": max_risk_level,
            "allowed_action_ids": allowed_action_ids or [],
            "allowed_connection_ids": allowed_connection_ids or [],
        }
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        return self._client.post(f"/agents/{agent_id}/delegations", json=body)

    def get(self, invocation_id: str) -> dict:
        return self._client.get(f"/actions/{invocation_id}")["invocation"]

    def get_result(self, invocation_id: str) -> Any:
        """What the Action produced, for example the messages a list returned.

        Only for the agent this client is authenticated as, and only once the
        invocation is ``executed``. Raises :class:`ActionResultUnavailable` with
        the server's reason otherwise, because "not run yet", "expired" and
        "cannot be read" each lead somewhere different, and none of them is a
        reason to run the Action again.
        """
        body = self._client.get(f"/actions/{invocation_id}")
        if "result" in body:
            return body["result"]
        raise ActionResultUnavailable(
            invocation_id,
            str(body.get("result_unavailable") or "No result was returned for this invocation."),
        )

    def cancel(self, invocation_id: str) -> dict:
        return self._client.post(f"/actions/{invocation_id}/cancel")["invocation"]

    def wait_for_invocation(
        self,
        invocation_id: str,
        interval_seconds: float = 3.0,
        timeout_seconds: float = 600.0,
    ) -> dict:
        """Poll until the invocation reaches a terminal state.

        POLLS. It re-reads state and never re-submits, because a resubmission on
        a network blip would send a second email the caller cannot learn about.
        A failed read propagates rather than being swallowed into an unbounded
        wait.

        Returns ``execution_indeterminate`` rather than raising on it: that
        state means the call may or may not have taken effect, and turning it
        into an exception invites the retry that must not happen.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            invocation = self.get(invocation_id)
            if invocation.get("state") in ACTION_TERMINAL_STATES:
                return invocation
            if time.monotonic() >= deadline:
                raise ActionTimeout(invocation_id, str(invocation.get("state")))
            time.sleep(interval_seconds)


def needs_human_resolution(invocation: dict) -> bool:
    """True when the outcome is genuinely unknown and a person must look.

    Exported because the alternative is every caller writing the string
    comparison themselves and half of them lumping it in with failure - which is
    the one classification that leads to a duplicate send.
    """
    return invocation.get("state") == "execution_indeterminate"


def did_execute(invocation: dict) -> bool:
    """True when the Action ran and Contro1 observed the provider's response."""
    return invocation.get("state") == "executed"
