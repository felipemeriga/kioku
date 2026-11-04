"""Native completions behind explicit operation policy, independent of SDK objects."""

import json
import os
from dataclasses import dataclass
from uuid import uuid4

from services.ai.accounting import record_job_usage
from services.ai.client import ExecutionError, ExecutionResult, TsukaiClient
from services.ai.registry import TASK_POLICIES, engine_for
from services.ai.scope import ExecutionScope, operation_scope, sign_capability


@dataclass(frozen=True)
class TextBlock:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class Completion:
    content: list[TextBlock]
    id: str
    model: str
    execution: ExecutionResult
    stop_reason: str = "end_turn"


def client_for(scope: ExecutionScope, operation: str, profile: str | None) -> TsukaiClient:
    return TsukaiClient(
        os.environ["TSUKAI_URL"],
        os.environ["TSUKAI_SERVICE_TOKEN"],
        lambda: sign_capability(scope, operation, profile),
        admission_capability=lambda request: sign_capability(
            scope, operation, profile, request=request
        ),
    )


def native_completion(
    *,
    operation: str,
    model: str,
    messages: list[dict],
    system: str | None,
    max_tokens: int,
    tools: list | None,
    fallback_scope: ExecutionScope | None = None,
) -> Completion | None:
    scope = operation_scope(operation) or fallback_scope
    if engine_for(operation, scope.owner_id if scope else None) == "api":
        return None
    if scope is None:
        raise PermissionError("native execution requires authenticated scope")
    if scope.caller == "mihari":
        raise ExecutionError("direct_route_required", "Mihari must submit directly to Tsukai")
    policy = TASK_POLICIES[operation]
    if tools or policy.tools:
        raise ExecutionError("harness_required", "chat must use the native conversation bridge")
    # Text-only completions deliberately reject vision/tool blocks until tested.
    for message in messages:
        content = message.get("content")
        if not isinstance(content, str) and not (
            isinstance(content, list) and all(block.get("type") == "text" for block in content)
        ):
            raise ExecutionError("unsupported_content")
    profile = "metadata_child" if scope.ai_depth else "completion"
    request = {
        "schema_version": 1,
        "idempotency_key": str(uuid4()),
        "owner_id": scope.owner_id,
        "caller": scope.caller,
        "operation": operation,
        "profile": profile,
        "prompt": json.dumps(messages, ensure_ascii=False),
        "system_prompt": system or "",
        "model": model,
        "max_tokens": max_tokens,
        "max_turns": 3,
        "folder_ids": list(scope.folder_ids),
        "tool_allowlist": [],
        "ai_depth": scope.ai_depth,
    }
    for name in ("parent_job_id", "root_job_id"):
        value = getattr(scope, name)
        if value:
            request[name] = value
    client = client_for(scope, operation, profile)
    try:
        result = client.complete(request)
    finally:
        try:
            if client.last_job_id:
                record_job_usage(client, scope, operation, model, client.last_job_id)
        finally:
            client.close()
    return Completion([TextBlock(result.text)], result.job_id, model, result)
