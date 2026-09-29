"""Report what an agent did, from the code around it rather than from the model.

A trace is only as complete as the thing that writes it. A model told to
"always report" can skip it, forget it, or describe something else. So the
reporting belongs in the runtime: a hook or wrapper that runs around every tool
call, that the model cannot see and cannot skip.

    from centcom import CentcomClient
    from centcom.tracing import TraceRun

    client = CentcomClient(api_key=os.environ["CONTRO1_AGENT_CREDENTIAL"])
    run = TraceRun(client, source="langgraph", fail_closed=True)

    lookup_order = run.wrap(lookup_order)          # every call is reported
    researcher = run.sub_agent("researcher")       # a named part, same trace tree

``fail_closed=True`` means a tool whose start could not be recorded does not
run: the wrapper raises ``TraceReportError`` instead. Without it, a report that
fails is dropped and the tool runs, which keeps an outage of the trace from
becoming an outage of the agent. Choose per tool: fail closed for anything that
changes something, open for reads.

Framework hooks built on this live in ``centcom.hooks``.
"""

from __future__ import annotations

import functools
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_OUTPUT_LIMIT = 2000


class TraceReportError(RuntimeError):
    """Contro1 could not record a step, and the run was set to fail closed."""


def new_trace_id() -> str:
    """A fresh trace id: one per run, passed to every step of it."""
    return f"trc_{secrets.token_hex(16)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary(value: Any) -> str:
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= _OUTPUT_LIMIT else text[: _OUTPUT_LIMIT - 15] + "...[truncated]"


def _plain(value: Any, depth: int = 0) -> Any:
    """JSON-safe: primitives pass, containers recurse a few levels, anything else is repr'd."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if depth >= 4:
        return _summary(value)
    if isinstance(value, dict):
        return {str(k): _plain(v, depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_plain(v, depth + 1) for v in list(value)[:50]]
    return _summary(value)


def _jsonable_input(value: Any) -> Optional[dict]:
    """Tool input as an object, or nothing. Never a stringified guess."""
    if isinstance(value, dict):
        return _plain(value)
    return None


class TraceRun:
    """One run of one agent, reported step by step under one trace id.

    ``client`` may be a sub-agent view (``client.as_sub_agent(...)``); every
    record is then attributed to that part.
    """

    def __init__(
        self,
        client: Any,
        *,
        trace_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
        source: str = "custom",
        run_id: Optional[str] = None,
        fail_closed: bool = False,
    ) -> None:
        self.client = client
        self.trace_id = trace_id or new_trace_id()
        self.parent_trace_id = parent_trace_id
        self.source = source
        self.run_id = run_id
        self.fail_closed = fail_closed

    # -- structure ---------------------------------------------------------------

    def sub_agent(self, name: str, *, fail_closed: Optional[bool] = None) -> "TraceRun":
        """A named part of this agent, as a child run of this one.

        The part reports as itself (``Contro1-Sub-Agent``) under its own trace,
        linked to this run by ``parent_trace_id``, so the trace reads as a tree.
        """
        return TraceRun(
            self.client.as_sub_agent(name),
            parent_trace_id=self.trace_id,
            source=self.source,
            run_id=self.run_id,
            fail_closed=self.fail_closed if fail_closed is None else fail_closed,
        )

    # -- reporting ---------------------------------------------------------------

    def _source(self) -> dict:
        return {"integration": self.source, **({"run_id": self.run_id} if self.run_id else {})}

    def report(self, action: str, summary: str, *, tool_calls: Optional[list] = None,
               outcome: str = "success", severity: str = "info", metadata: Optional[dict] = None,
               fail_closed: Optional[bool] = None) -> Optional[dict]:
        """Record one step. Returns the record, or None when a non-strict report failed."""
        try:
            return self.client.log_action(
                action=action[:128],
                summary=summary[:2000],
                source=self._source(),
                outcome=outcome,
                severity=severity,
                trace_id=self.trace_id,
                parent_trace_id=self.parent_trace_id,
                tool_calls=tool_calls,
                metadata=metadata,
            )
        except Exception as error:  # noqa: BLE001 - any failure to record is the same failure
            strict = self.fail_closed if fail_closed is None else fail_closed
            if strict:
                raise TraceReportError(f"Contro1 did not record '{action}': {error}") from error
            return None

    def tool_started(self, name: str, tool_input: Any = None, *, fail_closed: Optional[bool] = None) -> float:
        """Record that a tool is about to run. Raises when failing closed and it could not."""
        call = {"name": name[:200], "started_at": _now_iso()}
        payload = _jsonable_input(tool_input)
        if payload is not None:
            call["input"] = payload
        self.report(f"tool.{name}.started", f"Calling {name}", tool_calls=[call], fail_closed=fail_closed)
        return time.time()

    def tool_finished(self, name: str, *, output: Any = None, error: Optional[BaseException] = None,
                      started: Optional[float] = None) -> None:
        """Record how a tool ended. Never raises: the tool has already run."""
        call: dict = {"name": name[:200], "outcome": "failure" if error else "success", "ended_at": _now_iso()}
        if started is not None:
            call["started_at"] = datetime.fromtimestamp(started, timezone.utc).isoformat().replace("+00:00", "Z")
        if error is not None:
            call["error"] = _summary(str(error))
        elif output is not None:
            call["output_summary"] = _summary(output)
        self.report(
            f"tool.{name}.{'failed' if error else 'finished'}",
            f"{name} {'failed' if error else 'returned'}",
            tool_calls=[call],
            outcome="failure" if error else "success",
            severity="warning" if error else "info",
            fail_closed=False,
        )

    @contextmanager
    def tool(self, name: str, tool_input: Any = None) -> Iterator[None]:
        """``with run.tool("lookup_order", {"order_id": id}): ...``"""
        started = self.tool_started(name, tool_input)
        try:
            yield
        except BaseException as error:
            self.tool_finished(name, error=error, started=started)
            raise
        self.tool_finished(name, started=started)

    def wrap(self, fn: F, name: Optional[str] = None) -> F:
        """Report every call of ``fn``: its start (strictly, if failing closed) and its end."""
        tool_name = name or getattr(fn, "__name__", "tool")

        @functools.wraps(fn)
        def run(*args: Any, **kwargs: Any) -> Any:
            started = self.tool_started(tool_name, kwargs or ({"args": list(args)} if args else None))
            try:
                result = fn(*args, **kwargs)
            except BaseException as error:
                self.tool_finished(tool_name, error=error, started=started)
                raise
            self.tool_finished(tool_name, output=result, started=started)
            return result

        return run  # type: ignore[return-value]
