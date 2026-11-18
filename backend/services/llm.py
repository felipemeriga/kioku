"""Claude task routing through the shared subscription; API billing is disabled."""

from enum import Enum

from services.ai.client import ExecutionError
from services.ai.facade import Completion, native_completion
from services.ai.scope import ExecutionScope
from services.usage_ledger import UsageAttribution, current_usage


class Task(str, Enum):
    """Logical tasks routed to specific Claude models. Single source of truth."""

    QUERY_REWRITE = "query_rewrite"
    MULTI_QUERY = "multi_query"
    # Index-time contextual retrieval: a short standalone blurb situating each
    # chunk within its parent document, prepended before embedding (and rerank).
    CONTEXTUAL = "contextual"
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
    # Periodic maintenance of existing briefing and documentation sections.
    FOLDER_SUMMARY_REGROUND = "folder_summary_reground"


MODEL_FOR_TASK: dict[Task, str] = {
    Task.QUERY_REWRITE: "claude-haiku-4-5-20251001",
    Task.MULTI_QUERY: "claude-haiku-4-5-20251001",
    Task.CONTEXTUAL: "claude-haiku-4-5-20251001",
    Task.IMAGE_OCR: "claude-haiku-4-5-20251001",
    Task.TEXT_TO_SQL: "claude-haiku-4-5-20251001",
    Task.EVAL_JUDGE: "claude-haiku-4-5-20251001",
    Task.RAG_AGENT: "claude-haiku-4-5-20251001",
    Task.RAG_AGENT_SONNET: "claude-sonnet-4-6",
    Task.FOLDER_SUMMARY_DOC: "claude-haiku-4-5-20251001",
    Task.FOLDER_SUMMARY_ROLLUP: "claude-haiku-4-5-20251001",
    Task.FOLDER_SUMMARY_REGROUND: "claude-haiku-4-5-20251001",
}


def get_client():
    """Deprecated compatibility entry point; never instantiate a billed API client."""
    raise ExecutionError(
        "api_deprecated", "Claude is available only through subscription execution"
    )


def api_only_client(task: Task):
    """Fail closed for old SDK consumers instead of silently billing an API key."""
    return get_client()


def complete(
    *,
    task: Task,
    messages: list[dict],
    system: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
    cache_system: bool = True,
    thinking_budget: int | None = None,
    attribution: UsageAttribution | None = None,
    capture_usage: bool = True,
) -> Completion:
    """Run a Claude completion routed by task.

    When cache_system=True, attaches cache_control: ephemeral on the system prompt
    and on the last tool. Markers are no-ops below per-model minimum thresholds
    (Haiku 2048, Sonnet/Opus 1024 input tokens) — safe to leave on.

    Pass thinking_budget to enable extended thinking (must be < max_tokens).
    """
    active = current_usage()
    scoped = attribution or (active[0] if active else None)
    native = native_completion(
        operation=task.value,
        model=MODEL_FOR_TASK[task],
        messages=messages,
        system=system,
        max_tokens=max_tokens,
        tools=tools,
        fallback_scope=(
            ExecutionScope(
                scoped.user_id,
                (scoped.folder_id,) if scoped.folder_id else (),
                caller="mihari" if scoped.source == "mihari" else "backend",
                conversation_id=scoped.conversation_id,
            )
            if scoped
            else None
        ),
    )
    if native is not None:
        return native
    raise ExecutionError("subscription_unavailable", "Subscription execution returned no result")


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
    """Legacy SDK streaming is disabled; chat uses the native streaming bridge."""
    raise ExecutionError(
        "native_stream_required", "Use the subscription chat or maintenance bridge"
    )
