"""Strands Agents: report every tool call through a hook provider.

    from strands import Agent
    from centcom.hooks.strands import Contro1HookProvider

    agent = Agent(tools=[...], hooks=[Contro1HookProvider(client, fail_closed=True)])

One provider is one run. Failing closed raises from the before-tool hook, so a
tool whose start Contro1 could not record does not run.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..tracing import TraceRun

try:  # pragma: no cover - optional dependency
    from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
except ImportError as error:  # pragma: no cover
    raise ImportError("centcom.hooks.strands needs Strands Agents: pip install strands-agents") from error


class Contro1HookProvider(HookProvider):
    def __init__(self, client: Any, *, fail_closed: bool = False, source: str = "strands",
                 trace_id: Optional[str] = None) -> None:
        self.run = TraceRun(client, trace_id=trace_id, source=source, fail_closed=fail_closed)
        self._started: dict[str, float] = {}

    @property
    def trace_id(self) -> str:
        return self.run.trace_id

    def register_hooks(self, registry: HookRegistry, **_: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)
        registry.add_callback(AfterToolCallEvent, self._after)

    def _before(self, event: Any) -> None:
        use = event.tool_use or {}
        key = str(use.get("toolUseId") or use.get("name"))
        self._started[key] = self.run.tool_started(str(use.get("name", "tool")), use.get("input"))

    def _after(self, event: Any) -> None:
        use = event.tool_use or {}
        key = str(use.get("toolUseId") or use.get("name"))
        started = self._started.pop(key, time.time())
        error = getattr(event, "exception", None)
        result = getattr(event, "result", None)
        failed = error is not None or (isinstance(result, dict) and result.get("status") == "error")
        self.run.tool_finished(
            str(use.get("name", "tool")),
            output=None if failed else result,
            error=error if error is not None else (RuntimeError("tool returned an error") if failed else None),
            started=started,
        )
