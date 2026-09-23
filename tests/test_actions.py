"""The Action Gateway in the Python SDK.

WHAT THIS HAS TO PROVE:

* ``client.actions`` exists on the published package. It did not: the site
  documented ``client.actions.invoke`` while ``pip install centcom`` shipped a
  client without it.
* The idempotency key travels as a header and is never invented.
* Waiting re-reads and never re-submits.
* The result comes back, and when it cannot, the reason does - as its own
  exception, not as a failed Action.

Run:  python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import os
import sys
import unittest

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from centcom import ActionResultUnavailable, CentcomClient, did_execute  # noqa: E402


class _Server:
    """A stand-in Gateway that records every call it receives."""

    def __init__(self, states, result_body):
        self.calls = []
        self._states = list(states)
        self._result_body = result_body

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.method == "POST" and request.url.path.endswith("/actions/invoke"):
            return httpx.Response(202, json={"ok": True, "invocation": {"invocation_id": "inv_1", "state": "awaiting_approval"}})
        if request.method == "GET" and request.url.path.endswith("/actions/inv_1"):
            state = self._states.pop(0) if len(self._states) > 1 else self._states[0]
            body = {"ok": True, "invocation": {"invocation_id": "inv_1", "state": state}}
            if state == "executed":
                body.update(self._result_body)
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"ok": False})


def _with_transport(server: _Server) -> CentcomClient:
    client = CentcomClient(api_key="cc_live_test", base_url="https://api.example/api/centcom/v1")
    client._http = httpx.Client(
        base_url=client.base_url,
        headers={"Authorization": "Bearer cc_live_test", "Content-Type": "application/json"},
        transport=httpx.MockTransport(server.handler),
    )
    return client


class ActionsTests(unittest.TestCase):
    def test_invoke_sends_the_key_as_a_header_and_invents_none(self):
        server = _Server(["executed"], {"result": {"messages": []}})
        client = _with_transport(server)

        client.actions.invoke(
            "gmail.message.send", {"to": "a@example.com"}, "agent_principal", "shared",
            connection_id="conn_1", idempotency_key="order-42-reminder",
        )
        sent = server.calls[-1]
        self.assertEqual(sent.headers.get("Idempotency-Key"), "order-42-reminder")
        body = json.loads(sent.content)
        self.assertNotIn("idempotency_key", body, "the key is a header, not a body field")
        self.assertNotIn("agent_id", body, "identity comes from the credential, never the body")

        client.actions.invoke("gmail.message.list", {}, "agent_principal", "personal")
        self.assertIsNone(server.calls[-1].headers.get("Idempotency-Key"), "no key is invented")

    def test_waiting_rereads_and_never_resubmits(self):
        server = _Server(["awaiting_approval", "ready", "executed"], {"result": {"messages": [{"id": "m1"}]}})
        client = _with_transport(server)

        settled = client.actions.wait_for_invocation("inv_1", interval_seconds=0)
        self.assertTrue(did_execute(settled))
        self.assertTrue(all(call.method == "GET" for call in server.calls), "waiting must never POST")

    def test_the_result_is_returned(self):
        server = _Server(["executed"], {"result": {"messages": [{"id": "m1"}]}})
        client = _with_transport(server)
        self.assertEqual(client.actions.get_result("inv_1"), {"messages": [{"id": "m1"}]})

    def test_a_missing_result_says_why_and_is_not_a_failure(self):
        reason = "This action succeeded, but its result has passed its retention period."
        server = _Server(["executed"], {"result_unavailable": reason})
        client = _with_transport(server)
        with self.assertRaises(ActionResultUnavailable) as raised:
            client.actions.get_result("inv_1")
        self.assertIn("retention", raised.exception.reason)


if __name__ == "__main__":
    unittest.main()
