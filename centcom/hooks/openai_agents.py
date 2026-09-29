"""OpenAI Agents SDK: report every tool call through run hooks.

    from agents import Runner
    from centcom.hooks.openai_agents import Contro1RunHooks

    hooks = Contro1RunHooks(client, fail_closed=True, per_agent=True)
    await Runner.run(triage_agent, "Refund order 1842", hooks=hooks)

With ``per_agent=True`` each agent in the run (triage, a handoff target, an
agent used as a tool) reports as a named part of this Contro1 agent, so the
trace shows which one called which tool. One hooks object is one run.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..tracing import TraceRun

try:  # pragma: no cover - optional dependency
    from agents import RunHooks
except ImportError as error:  # pragma: no cover
    raise ImportError("centcom.hooks.openai_agents needs the OpenAI Agents SDK: pip install openai-agents") from error


class Contro1RunHooks(RunHooks):
    """Reports each tool start and end, optionally per agent in the run."""

    def __init__(self, client: Any, *, fail_closed: bool = False, per_agent: bool = False,
                 source: str = "openai-agents", trace_id: Optional[str] = None) -> None:
        super().__init__()
        self.run = TraceRun(client, trace_id=trace_id, source=source, fail_closed=fail_closed)
        self._per_agent = per_agent
        self._parts: dict[str, TraceRun] = {}
        self._started: dict[tuple[str, str], float] = {}

    @property
    def trace_id(self) -> str:
        return self.run.trace_id

    def _run_for(self, agent: Any) -> TraceRun:
        if not self._per_agent:
            return self.run
        name = str(getattr(agent, "name", "") or "agent")[:64]
        if name not in self._parts:
            self._parts[name] = self.run.sub_agent(name)
        return self._parts[name]

    async def on_tool_start(self, context: Any, agent: Any, tool: Any) -> None:
        name = str(getattr(tool, "name", "tool"))
        arguments = getattr(context, "tool_arguments", None)
        tool_input = None
        if isinstance(arguments, str):
            try:
                import json
                parsed = json.loads(arguments)
                tool_input = parsed if isinstance(parsed, dict) else None
            except ValueError:
                tool_input = None
        started = self._run_for(agent).tool_started(name, tool_input)
        self._started[(str(getattr(agent, "name", "")), name)] = started

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: Any) -> None:
        name = str(getattr(tool, "name", "tool"))
        started = self._started.pop((str(getattr(agent, "name", "")), name), time.time())
        self._run_for(agent).tool_finished(name, output=result, started=started)
