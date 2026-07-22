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
    FOLDER_SUMMARY_DOC = "folder_summary_doc"
    FOLDER_SUMMARY_ROLLUP = "folder_summary_rollup"


MODEL_FOR_TASK: dict[Task, str] = {
    Task.METADATA: "claude-haiku-4-5-20251001",
    Task.QUERY_REWRITE: "claude-haiku-4-5-20251001",
    Task.MULTI_QUERY: "claude-haiku-4-5-20251001",
    Task.IMAGE_OCR: "claude-haiku-4-5-20251001",
    Task.TEXT_TO_SQL: "claude-haiku-4-5-20251001",
    Task.EVAL_JUDGE: "claude-haiku-4-5-20251001",
    Task.RAG_AGENT: "claude-haiku-4-5-20251001",
    Task.FOLDER_SUMMARY_DOC: "claude-haiku-4-5-20251001",
    Task.FOLDER_SUMMARY_ROLLUP: "claude-haiku-4-5-20251001",
}


@cache
def get_client() -> anthropic.Anthropic:
    """Lazy singleton Anthropic client, LangSmith-wrapped for tracing."""
    return wrap_anthropic(
        anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=60.0,
        )
    )


def _build_kwargs(
    *,
    task: Task,
    messages: list[dict],
    system: str | None,
    tools: list[dict] | None,
    max_tokens: int,
    cache_system: bool,
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
    return kwargs


def complete(
    *,
    task: Task,
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
    cache_system: bool = True,
) -> anthropic.types.Message:
    """Run a Claude completion routed by task.

    When cache_system=True, attaches cache_control: ephemeral on the system prompt
    and on the last tool. Markers are no-ops below per-model minimum thresholds
    (Haiku 2048, Sonnet/Opus 1024 input tokens) — safe to leave on.
    """
    kwargs = _build_kwargs(
        task=task, messages=messages, system=system, tools=tools,
        max_tokens=max_tokens, cache_system=cache_system,
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
):
    """Streaming variant. Returns a context manager yielding a stream —
    caller uses `with stream_complete(...) as s: for text in s.text_stream: ...`.

    All routing / cache-control / tool schema handling matches complete()
    so you can freely swap between them without behavior drift.
    """
    kwargs = _build_kwargs(
        task=task, messages=messages, system=system, tools=tools,
        max_tokens=max_tokens, cache_system=cache_system,
    )
    return get_client().messages.stream(**kwargs)
