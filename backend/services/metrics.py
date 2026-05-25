"""Per-request retrieval-pipeline metrics collector.

Mirror of services/timing.py for stage-state diagnostics (counts, overlaps, score
distributions) — not wall-clock. Prints one grouped [metrics] block on request
exit so the diagnostics are readable as a snapshot rather than interleaved with
[perf] lines.

Env-gated by RAG_METRICS=1. Default off so prod stderr stays quiet; turn on for
local dev, staging, or one-off prod debugging.

Thread-safety: held in a contextvars.ContextVar so it's per-request without
threading state through every signature. ThreadPoolExecutor workers DO NOT
inherit contextvars automatically — use submit_with_context() at every fan-out
site instead of plain pool.submit().
"""

from __future__ import annotations

import contextvars
import os
import sys
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from typing import Any, Iterator


class RequestMetrics:
    """Accumulates per-stage metric records for a single request.

    Records are insertion-ordered. Concurrent writes from pool workers are
    serialized by a lock.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._stages: list[tuple[str, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def add(self, stage: str, **kvs: Any) -> None:
        with self._lock:
            self._stages.append((stage, kvs))

    def render(self) -> str:
        lines = [f"[metrics] === {self.name} ==="]
        for stage, kvs in self._stages:
            kv_str = " ".join(f"{k}={_fmt(v)}" for k, v in kvs.items())
            lines.append(f"[metrics]   {stage}: {kv_str}")
        return "\n".join(lines)


_current: contextvars.ContextVar[RequestMetrics | None] = contextvars.ContextVar(
    "rag_metrics_current", default=None
)


def _fmt(v: Any) -> str:
    """Compact, deterministic value formatting for stderr."""
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _enabled() -> bool:
    return os.environ.get("RAG_METRICS") == "1"


@contextmanager
def collect_request(name: str) -> Iterator[RequestMetrics | None]:
    """Open a per-request collector; prints the grouped block on exit.

    Yields None when RAG_METRICS is disabled so callers can still wrap their
    code in `with collect_request(...)` without conditional logic.
    """
    if not _enabled():
        yield None
        return

    metrics = RequestMetrics(name)
    token = _current.set(metrics)
    try:
        yield metrics
    finally:
        _current.reset(token)
        print(metrics.render(), file=sys.stderr, flush=True)


def record(stage: str, **kvs: Any) -> None:
    """Record metrics for a stage. No-op if no active collector or if disabled.

    Safe to call from anywhere — production code, tests, MCP path. The MCP
    direct-search entry point does not open a collector, so record() no-ops
    there, which is the correct behavior (no metrics noise on MCP autocompletes).
    """
    metrics = _current.get()
    if metrics is None:
        return
    metrics.add(stage, **kvs)


def submit_with_context(
    pool: ThreadPoolExecutor, fn: Callable, *args: Any, **kwargs: Any
) -> Future:
    """Submit a callable to the pool with the current contextvars context.

    ThreadPoolExecutor.submit() runs the callable in a fresh context, so any
    record() calls inside `fn` would be no-ops. This helper snapshots the
    current context and runs `fn` inside it, so the collector propagates.
    """
    ctx = copy_context()
    return pool.submit(ctx.run, fn, *args, **kwargs)
