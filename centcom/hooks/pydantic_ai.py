"""Pydantic AI: report every tool call by wrapping the agent's toolset.

    from pydantic_ai import Agent
    from pydantic_ai.toolsets import FunctionToolset
    from centcom.hooks.pydantic_ai import contro1_toolset

    tools = FunctionToolset([lookup_order, issue_refund])
    agent = Agent("anthropic:claude-sonnet-5", toolsets=[contro1_toolset(tools, client, fail_closed=True)])

Every call goes through ``call_tool``, so its start is recorded before the tool
runs and its end after. Failing closed raises from there: a tool whose start
Contro1 could not record does not run. One wrapped toolset is one run; wrap
again (or pass ``trace_id``) for the next.

Already exporting OpenTelemetry (``instrument=True`` / Logfire)? Pointing the
exporter at Contro1's OTLP endpoint needs no code change at all; this wrapper
is for failing closed, which an exporter cannot do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..tracing import TraceRun

try:  # pragma: no cover - optional dependency
    from pydantic_ai.toolsets import AbstractToolset, WrapperToolset
except ImportError as error:  # pragma: no cover
    raise ImportError("centcom.hooks.pydantic_ai needs Pydantic AI: pip install pydantic-ai-slim") from error


@dataclass
class Contro1Toolset(WrapperToolset):
    """A toolset that reports each call of the one it wraps."""

    run: TraceRun = None  # type: ignore[assignment]

    @property
    def trace_id(self) -> str:
        return self.run.trace_id

    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: Any, tool: Any) -> Any:
        started = self.run.tool_started(name, tool_args)
        try:
            result = await self.wrapped.call_tool(name, tool_args, ctx, tool)
        except BaseException as error:
            self.run.tool_finished(name, error=error, started=started)
            raise
        self.run.tool_finished(name, output=result, started=started)
        return result


def contro1_toolset(toolset: AbstractToolset, client: Any, *, fail_closed: bool = False,
                    source: str = "pydantic-ai", trace_id: Optional[str] = None) -> Contro1Toolset:
    """Wrap ``toolset`` so its calls are reported to Contro1 under one trace."""
    return Contro1Toolset(
        wrapped=toolset,
        run=TraceRun(client, trace_id=trace_id, source=source, fail_closed=fail_closed),
    )
