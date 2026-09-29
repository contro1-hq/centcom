"""LangChain and LangGraph: report every tool call through a callback handler.

    from centcom.hooks.langchain import Contro1TraceHandler

    handler = Contro1TraceHandler(client, fail_closed=True)
    graph.invoke(inputs, config={"callbacks": [handler]})

One handler is one run: it keeps one trace id for everything it sees. Make a
new handler per run (or call ``handler.new_run()``).

Failing closed works through LangChain's own switch: the handler sets
``raise_error``, so a start that could not be recorded raises out of
``on_tool_start`` and the tool does not run.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..tracing import TraceRun

try:  # pragma: no cover - optional dependency
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError as error:  # pragma: no cover
    raise ImportError("centcom.hooks.langchain needs langchain-core: pip install langchain-core") from error


class Contro1TraceHandler(BaseCallbackHandler):
    """Reports each tool start and end to Contro1 under one trace id."""

    def __init__(self, client: Any, *, fail_closed: bool = False, source: str = "langgraph",
                 trace_id: Optional[str] = None, run_id: Optional[str] = None) -> None:
        super().__init__()
        self.raise_error = fail_closed
        self._source = source
        self._fail_closed = fail_closed
        self.run = TraceRun(client, trace_id=trace_id, source=source, run_id=run_id, fail_closed=fail_closed)
        self._started: dict[Any, tuple[str, float]] = {}

    @property
    def trace_id(self) -> str:
        return self.run.trace_id

    def new_run(self) -> str:
        """Start a new trace for the next run; returns its id."""
        self.run = TraceRun(self.run.client, source=self._source, fail_closed=self._fail_closed)
        self._started.clear()
        return self.run.trace_id

    def on_tool_start(self, serialized: dict, input_str: str, *, run_id: Any = None,
                      inputs: Optional[dict] = None, **kwargs: Any) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        started = self.run.tool_started(name, inputs if isinstance(inputs, dict) else {"input": input_str})
        self._started[run_id] = (name, started)

    def on_tool_end(self, output: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        name, started = self._started.pop(run_id, (kwargs.get("name") or "tool", time.time()))
        self.run.tool_finished(name, output=getattr(output, "content", output), started=started)

    def on_tool_error(self, error: BaseException, *, run_id: Any = None, **kwargs: Any) -> None:
        name, started = self._started.pop(run_id, (kwargs.get("name") or "tool", time.time()))
        self.run.tool_finished(name, error=error, started=started)
