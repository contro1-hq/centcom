"""CrewAI and Pydantic AI hooks, against the real frameworks when installed.

Each test is skipped when its framework is not installed; CI for the SDK does
not pull them in. Run with them present:

    pip install crewai pydantic-ai-slim
    python -m unittest tests.test_framework_hooks
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeClient:
    """Records log_action calls; fails every one when ``fail`` is set."""

    def __init__(self, fail: bool = False, name: str | None = None, records: list | None = None) -> None:
        self.fail, self.name = fail, name
        self.records = records if records is not None else []

    def log_action(self, **kwargs):
        if self.fail:
            raise RuntimeError("Contro1 unreachable")
        self.records.append((self.name, kwargs["action"]))
        return {"ok": True}

    def as_sub_agent(self, name: str) -> "_FakeClient":
        return _FakeClient(self.fail, name, self.records)


try:
    import pydantic_ai  # noqa: F401
    HAVE_PYDANTIC_AI = True
except ImportError:
    HAVE_PYDANTIC_AI = False

try:
    import crewai.hooks  # noqa: F401
    HAVE_CREWAI = True
except ImportError:
    HAVE_CREWAI = False


@unittest.skipUnless(HAVE_PYDANTIC_AI, "pydantic-ai not installed")
class PydanticAiHookTest(unittest.TestCase):
    def _agent(self, client, ran, **options):
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel
        from pydantic_ai.toolsets import FunctionToolset
        from centcom.hooks.pydantic_ai import contro1_toolset

        def lookup_order(order_id: str) -> str:
            ran.append(order_id)
            return "charged twice"

        return Agent(TestModel(), toolsets=[contro1_toolset(FunctionToolset([lookup_order]), client, **options)])

    def test_reports_start_and_end(self):
        client, ran = _FakeClient(), []
        self._agent(client, ran).run_sync("go")
        self.assertTrue(ran)
        self.assertEqual([a for _, a in client.records], ["tool.lookup_order.started", "tool.lookup_order.finished"])

    def test_fail_closed_tool_does_not_run(self):
        from centcom.tracing import TraceReportError
        ran = []
        with self.assertRaises(TraceReportError):
            self._agent(_FakeClient(fail=True), ran, fail_closed=True).run_sync("go")
        self.assertEqual(ran, [])


@unittest.skipUnless(HAVE_CREWAI, "crewai not installed")
class CrewAiHookTest(unittest.TestCase):
    """Drives CrewAI's own hook dispatch, the call its executors make around a tool."""

    class _Member:
        role = "Refund agent"

    def _context(self, **extra):
        from crewai.hooks import ToolCallHookContext
        return ToolCallHookContext(tool_name="issue_refund", tool_input={"amount": 240}, tool=None,
                                   agent=self._Member(), **extra)

    def test_reports_per_crew_member_and_uninstalls(self):
        from crewai.hooks import get_before_tool_call_hooks
        from crewai.hooks.tool_hooks import run_after_tool_call_hooks, run_before_tool_call_hooks
        from centcom.hooks.crewai import Contro1CrewHooks

        client = _FakeClient()
        with Contro1CrewHooks(client, per_agent=True):
            self.assertFalse(run_before_tool_call_hooks(self._context()))
            run_after_tool_call_hooks(self._context(tool_result="refunded"))
        self.assertEqual(client.records, [
            ("Refund agent", "tool.issue_refund.started"),
            ("Refund agent", "tool.issue_refund.finished"),
        ])
        self.assertEqual(get_before_tool_call_hooks(), [])

    def test_fail_closed_blocks_the_call(self):
        from crewai.hooks.tool_hooks import run_after_tool_call_hooks, run_before_tool_call_hooks
        from centcom.hooks.crewai import Contro1CrewHooks

        client = _FakeClient(fail=True)
        with Contro1CrewHooks(client, fail_closed=True):
            self.assertTrue(run_before_tool_call_hooks(self._context()), "the call is blocked")
            run_after_tool_call_hooks(self._context(tool_result="blocked"))
        self.assertEqual(client.records, [])


if __name__ == "__main__":
    unittest.main()
