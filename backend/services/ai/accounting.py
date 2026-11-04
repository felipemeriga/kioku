"""Native per-job usage is a list-price equivalent, never API cash billing."""

from db.client import get_supabase_thread_safe
from services.ai.client import ExecutionResult
from services.ai.scope import ExecutionScope


def record_native_usage(
    scope: ExecutionScope,
    operation: str,
    model: str,
    result: ExecutionResult,
    *,
    source: str | None = None,
    outcome: str | None = None,
):
    usage = result.usage or {}
    row = {
        "job_id": result.job_id,
        "attempt_id": result.attempt_id or "unknown",
        "owner_id": scope.owner_id,
        "conversation_id": scope.conversation_id,
        "outcome": outcome,
        "operation": operation,
        "source": source or scope.caller,
        "model": model,
        "billing_mode": "subscription",
        "list_equivalent_usd": usage.get("list_equivalent_usd"),
        "complete": bool(usage.get("complete", False)),
        "usage": result.usage,
    }
    get_supabase_thread_safe().table("tsukai_native_usage").upsert(
        row, on_conflict="job_id,attempt_id"
    ).execute()


def record_job_usage(
    client,
    scope: ExecutionScope,
    operation: str,
    model: str,
    job_id: str,
    *,
    source: str | None = None,
):
    attempts = client.usage(job_id)["attempts"]
    for attempt in attempts:
        result = ExecutionResult(
            job_id,
            "",
            None,
            attempt.get("usage"),
            None,
            attempt["attempt_id"],
        )
        record_native_usage(
            scope,
            operation,
            attempt.get("model") or model,
            result,
            source=source,
            outcome=attempt.get("status"),
        )
    return attempts
