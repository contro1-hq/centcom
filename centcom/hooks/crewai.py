"""CrewAI: report every tool call through CrewAI's tool-call hooks.

    from centcom.hooks.crewai import Contro1CrewHooks

    with Contro1CrewHooks(client, fail_closed=True, per_agent=True):
        crew.kickoff(inputs={"order_id": "1842"})

CrewAI's tool hooks are global to the process, so the hooks are installed for
the ``with`` block (or between ``install()`` and ``uninstall()``) and one
object is one run. With ``per_agent=True`` each crew member (its ``role``)
reports as a named part of this Contro1 agent.

Failing closed returns ``False`` from the before-tool hook, which is how
CrewAI blocks a call: an exception there would be swallowed and the tool
would run anyway.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..tracing import TraceReportError, TraceRun

try:  # pragma: no cover - optional dependency
    from crewai.hooks import (
        register_after_tool_call_hook,
        register_before_tool_call_hook,
        unregister_after_tool_call_hook,
        unregister_before_tool_call_hook,
    )
except ImportError as error:  # pragma: no cover
    raise ImportError("centcom.hooks.crewai needs CrewAI 1.x with tool hooks: pip install -U crewai") from error


class Contro1CrewHooks:
    def __init__(self, client: Any, *, fail_closed: bool = False, per_agent: bool = False,
                 source: str = "crewai", trace_id: Optional[str] = None) -> None:
        self.run = TraceRun(client, trace_id=trace_id, source=source, fail_closed=fail_closed)
        self._per_agent = per_agent
        self._parts: dict[str, TraceRun] = {}
        # Per agent and tool, a stack of start times: None marks a blocked call.
        self._started: dict[tuple[str, str], list[Optional[float]]] = {}
        self._installed = False

    @property
    def trace_id(self) -> str:
        return self.run.trace_id

    def install(self) -> "Contro1CrewHooks":
        if not self._installed:
            register_before_tool_call_hook(self._before)
            register_after_tool_call_hook(self._after)
            self._installed = True
        return self

    def uninstall(self) -> None:
        if self._installed:
            unregister_before_tool_call_hook(self._before)
            unregister_after_tool_call_hook(self._after)
            self._installed = False

    def __enter__(self) -> "Contro1CrewHooks":
        return self.install()

    def __exit__(self, *_: Any) -> None:
        self.uninstall()

    def _agent_name(self, context: Any) -> str:
        agent = getattr(context, "agent", None)
        return str(getattr(agent, "role", "") or "agent")[:64]

    def _run_for(self, agent_name: str) -> TraceRun:
        if not self._per_agent:
            return self.run
        if agent_name not in self._parts:
            self._parts[agent_name] = self.run.sub_agent(agent_name)
        return self._parts[agent_name]

    def _before(self, context: Any) -> Optional[bool]:
        agent_name = self._agent_name(context)
        tool = str(getattr(context, "tool_name", "") or "tool")
        stack = self._started.setdefault((agent_name, tool), [])
        try:
            stack.append(self._run_for(agent_name).tool_started(tool, getattr(context, "tool_input", None)))
        except TraceReportError:
            stack.append(None)
            return False
        return None

    def _after(self, context: Any) -> None:
        agent_name = self._agent_name(context)
        tool = str(getattr(context, "tool_name", "") or "tool")
        stack = self._started.get((agent_name, tool)) or []
        started = stack.pop() if stack else time.time()
        if started is None:
            return  # blocked before it ran; the refusal is already the record
        self._run_for(agent_name).tool_finished(
            tool,
            output=getattr(context, "tool_result", None),
            started=started,
        )
        return None
