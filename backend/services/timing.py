"""Lightweight perf timing helpers for request-level latency debugging.

Prints to stderr so it doesn't interleave with the SSE response stream.
Indent levels stack visually:

    [perf] === rag chat turn ===
    [perf]   round 1: anthropic call: 980ms
    [perf]   tool: knowledge_base_search: 5420ms
    [perf]     search_documents (full): 5380ms
    [perf]       phase1: rewrite + multi_query: 1100ms
    [perf]   round 2: anthropic call: 1850ms
    [perf] === rag chat turn total: 8540ms ===
"""

import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager


def _fmt(elapsed_s: float) -> str:
    return f"{elapsed_s * 1000:.0f}ms"


@contextmanager
def stage(name: str, indent: int = 1) -> Iterator[None]:
    """Time a span and print its wall-clock duration on exit."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        prefix = "  " * indent
        print(f"[perf] {prefix}{name}: {_fmt(time.monotonic() - t0)}", file=sys.stderr, flush=True)


@contextmanager
def request(name: str) -> Iterator[None]:
    """Top-level request marker — bracketed header + total line."""
    print(f"[perf] === {name} ===", file=sys.stderr, flush=True)
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        print(
            f"[perf] === {name} total: {_fmt(elapsed)} ===\n",
            file=sys.stderr,
            flush=True,
        )
