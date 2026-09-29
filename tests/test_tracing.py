"""Traces reported from the runtime, and sub-agents.

WHAT THIS HAS TO PROVE:

* ``as_sub_agent`` sends the Contro1-Sub-Agent header on every call from that
  view, Actions included, and the parent view does not.
* A run keeps one trace id; a sub-agent's run links to it by parent_trace_id.
* Failing closed means a tool whose start could not be recorded DOES NOT RUN.
* Failing open means it does.

Run:  python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import os
import sys
import unittest

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from centcom import CentcomClient  # noqa: E402
from centcom.tracing import TraceReportError, TraceRun, new_trace_id  # noqa: E402


class _Server:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.down:
            return httpx.Response(503, json={"message": "unavailable"})
        if request.url.path.endswith("/actions/invoke"):
            return httpx.Response(201, json={"invocation": {"invocation_id": "inv_1", "state": "executed"}})
        return httpx.Response(201, json={"id": "rec_1"})

    def bodies(self) -> list[dict]:
        return [json.loads(call.content or b"{}") for call in self.calls]


def _client(server: _Server) -> CentcomClient:
    return CentcomClient(transport=httpx.MockTransport(server.handler), base_url="https://example.test/api/centcom/v1")


class SubAgentTests(unittest.TestCase):
    def test_view_sends_the_header_and_the_parent_does_not(self) -> None:
        server = _Server()
        client = _client(server)
        researcher = client.as_sub_agent("researcher")
        researcher.log_action(action="tool.lookup", summary="s", source={"integration": "t"})
        researcher.actions.invoke("gmail.message.list", {}, authority_mode="agent_principal", account_mode="shared")
        client.log_action(action="tool.lookup", summary="s", source={"integration": "t"})
        headers = [call.headers.get("contro1-sub-agent") for call in server.calls]
        self.assertEqual(headers, ["researcher", "researcher", None])

    def test_names_are_bounded(self) -> None:
        client = _client(_Server())
        with self.assertRaises(ValueError):
            client.as_sub_agent("")
        with self.assertRaises(ValueError):
            client.as_sub_agent("x" * 65)


class TraceRunTests(unittest.TestCase):
    def test_one_trace_and_a_linked_sub_agent_run(self) -> None:
        server = _Server()
        run = TraceRun(_client(server), source="test")
        part = run.sub_agent("writer")
        run.report("step.one", "first")
        part.report("step.two", "second")
        first, second = server.bodies()
        self.assertEqual(first["trace_id"], run.trace_id)
        self.assertTrue(run.trace_id.startswith("trc_"))
        self.assertEqual(second["parent_trace_id"], run.trace_id)
        self.assertNotEqual(second["trace_id"], run.trace_id)

    def test_wrapped_tool_reports_start_and_end(self) -> None:
        server = _Server()
        run = TraceRun(_client(server))
        lookup = run.wrap(lambda order_id: {"order": order_id}, name="lookup_order")
        self.assertEqual(lookup(order_id="1842"), {"order": "1842"})
        start, end = server.bodies()
        self.assertEqual(start["tool_calls"][0]["input"], {"order_id": "1842"})
        self.assertEqual(end["tool_calls"][0]["outcome"], "success")

    def test_fail_closed_stops_the_tool(self) -> None:
        server = _Server()
        server.down = True
        ran = []
        refund = TraceRun(_client(server), fail_closed=True).wrap(lambda amount: ran.append(amount), name="refund")
        with self.assertRaises(TraceReportError):
            refund(amount=240)
        self.assertEqual(ran, [], "a tool whose start was not recorded must not run")

    def test_fail_open_runs_the_tool(self) -> None:
        server = _Server()
        server.down = True
        ran = []
        TraceRun(_client(server), fail_closed=False).wrap(lambda amount: ran.append(amount), name="read")(amount=1)
        self.assertEqual(ran, [1])

    def test_trace_ids_are_fresh(self) -> None:
        self.assertNotEqual(new_trace_id(), new_trace_id())


if __name__ == "__main__":
    unittest.main()
