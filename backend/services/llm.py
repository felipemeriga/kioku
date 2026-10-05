"""Central Anthropic LLM client: singleton, task→model routing, prompt caching."""

import os
from enum import Enum
from functools import cache

import anthropic
from langsmith.wrappers import wrap_anthropic


class Task(str, Enum):
    """Logical tasks routed to specific Claude models. Single source of truth."""

    METADATA = "metadata"
    QUERY_REWRITE = "query_rewrite"
    MULTI_QUERY = "multi_query"
    IMAGE_OCR = "image_ocr"
    TEXT_TO_SQL = "text_to_sql"
    EVAL_JUDGE = "eval_judge"
    RAG_AGENT = "rag_agent"
    # Sonnet route for the agentic chat. Model (Haiku vs Sonnet) and reasoning
    # (extended thinking on/off) are independent knobs now — RAG_AGENT is the
    # Haiku route, RAG_AGENT_SONNET the Sonnet route; either can run with or
    # without thinking (see rag._agent_params).
    RAG_AGENT_SONNET = "rag_agent_sonnet"
    FOLDER_SUMMARY_DOC = "folder_summary_doc"
    FOLDER_SUMMARY_ROLLUP = "folder_summary_rollup"
    # Periodic re-ground of the holistic briefing sections (architecture /
    # overview) from the repo's current key files — Sonnet for prose quality.
    FOLDER_SUMMARY_REGROUND = "folder_summary_reground"


MODEL_FOR_TASK: dict[Task, str] = {
    Task.METADATA: "claude-haiku-4-5-20251001",
    Task.QUERY_REWRITE: "claude-haiku-4-5-20251001",
    Task.MULTI_QUERY: "claude-haiku-4-5-20251001",
    Task.IMAGE_OCR: "claude-haiku-4-5-20251001",
    Task.TEXT_TO_SQL: "claude-haiku-4-5-20251001",
    Task.EVAL_JUDGE: "claude-haiku-4-5-20251001",
    Task.RAG_AGENT: "claude-haiku-4-5-20251001",
    Task.RAG_AGENT_SONNET: "claude-sonnet-4-6",
    Task.FOLDER_SUMMARY_DOC: "claude-haiku-4-5-20251001",
    Task.FOLDER_SUMMARY_ROLLUP: "claude-haiku-4-5-20251001",
    Task.FOLDER_SUMMARY_REGROUND: "claude-sonnet-4-6",
}

# Interleaved thinking lets the model reason BETWEEN tool calls within a single
# turn (plan → search → reflect → verify), not just once up front.
_INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"


def _tracing_enabled() -> bool:
    """True only when LangSmith tracing is explicitly turned on."""
    return os.getenv("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes") or (
        os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("1", "true", "yes")
    )


@cache
def get_client() -> anthropic.Anthropic:
    """Lazy singleton Anthropic client.

    LangSmith's ``wrap_anthropic`` (0.7.x) crashes the streaming path with
    anthropic >=0.84 — its ``_text_stream`` raises ``AttributeError: 'NoneType'
    object has no attribute 'outputs'`` mid-stream, which kills the SSE chat
    response before completion. Only apply the wrapper when tracing is actually
    enabled; otherwise use the raw client. (Re-enabling tracing needs a langsmith
    upgrade compatible with the current anthropic SDK.)
    """
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=60.0,
    )
    return wrap_anthropic(client) if _tracing_enabled() else client


def _build_kwargs(
    *,
    task: Task,
    messages: list[dict],
    system: str | None,
    tools: list[dict] | None,
    max_tokens: int,
    cache_system: bool,
    thinking_budget: int | None = None,
) -> dict:
    kwargs: dict = {
        "model": MODEL_FOR_TASK[task],
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        if cache_system:
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            kwargs["system"] = system
    if tools:
        if cache_system:
            tools = [*tools[:-1], {**tools[-1], "cache_control": {"type": "ephemeral"}}]
        kwargs["tools"] = tools
    if thinking_budget:
        # Extended thinking: the model emits reasoning before its answer/tool
        # calls. budget_tokens must be < max_tokens (thinking + output share it).
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        kwargs["extra_headers"] = {"anthropic-beta": _INTERLEAVED_THINKING_BETA}
    return kwargs


def complete(
    *,
    task: Task,
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
    cache_system: bool = True,
    thinking_budget: int | None = None,
) -> anthropic.types.Message:
    """Run a Claude completion routed by task.

    When cache_system=True, attaches cache_control: ephemeral on the system prompt
    and on the last tool. Markers are no-ops below per-model minimum thresholds
    (Haiku 2048, Sonnet/Opus 1024 input tokens) — safe to leave on.

    Pass thinking_budget to enable extended thinking (must be < max_tokens).
    """
    kwargs = _build_kwargs(
        task=task,
        messages=messages,
        system=system,
        tools=tools,
        max_tokens=max_tokens,
        cache_system=cache_system,
        thinking_budget=thinking_budget,
    )
    return get_client().messages.create(**kwargs)


def stream_complete(
    *,
    task: Task,
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
    cache_system: bool = True,
    thinking_budget: int | None = None,
):
    """Streaming variant. Returns a context manager yielding a stream —
    caller uses `with stream_complete(...) as s: for text in s.text_stream: ...`.

    All routing / cache-control / tool schema handling matches complete()
    so you can freely swap between them without behavior drift.
    """
    kwargs = _build_kwargs(
        task=task,
        messages=messages,
        system=system,
        tools=tools,
        max_tokens=max_tokens,
        cache_system=cache_system,
        thinking_budget=thinking_budget,
    )
    return get_client().messages.stream(**kwargs)
