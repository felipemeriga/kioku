"""Tool-disabled reserved child generates a typed plan; SQL remains parameterized."""

import json
from uuid import uuid4

from db.client import get_supabase_thread_safe
from services.ai.accounting import record_job_usage
from services.ai.client import ExecutionError
from services.ai.facade import client_for
from services.ai.scope import ExecutionScope

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "operation": {
            "type": "string",
            "enum": [
                "count_files",
                "count_chunks",
                "list_files",
                "source_types",
            ],
        },
        "source_type": {"type": ["string", "null"]},
        "filename": {"type": ["string", "null"]},
        "created_after": {"type": ["string", "null"]},
        "created_before": {"type": ["string", "null"]},
    },
    "required": ["operation", "source_type", "filename", "created_after", "created_before"],
}
ENVELOPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": 1},
        "outcome": {"enum": ["completed", "needs_input", "failed"]},
        "data": {"anyOf": [PLAN_SCHEMA, {"type": "null"}]},
        "missing_inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"field": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["field", "reason"],
                "additionalProperties": False,
            },
        },
        "failure": {"type": ["object", "null"]},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["schema_version", "outcome", "data", "missing_inputs", "failure", "warnings"],
}


def metadata_query(question: str, authority: dict) -> str:
    nested = bool(authority.get("job_id"))
    profile = "metadata_child" if nested else "completion"
    scope = ExecutionScope(
        authority["owner_id"],
        tuple(authority["folder_ids"]),
        caller="backend" if nested else "mcp",
        parent_job_id=authority.get("job_id"),
        root_job_id=authority.get("job_id"),
        ai_depth=1 if nested else 0,
        expires_at=authority.get("exp"),
    )
    request = {
        "schema_version": 1,
        "idempotency_key": str(uuid4()),
        "owner_id": scope.owner_id,
        "caller": scope.caller,
        "operation": "text_to_sql",
        "profile": profile,
        "folder_ids": list(scope.folder_ids),
        "tool_allowlist": [],
        "parent_job_id": scope.parent_job_id,
        "root_job_id": scope.root_job_id,
        "ai_depth": scope.ai_depth,
        "prompt": question,
        "system_prompt": (
            "Translate the question to a scoped document metadata plan. Count distinct files "
            "unless chunks are explicitly requested. Supported operations: count_files, "
            "count_chunks, list_files (bounded to 200), source_types. Filters are exact "
            "source_type, filename and optional ISO creation dates. You cannot run tools or "
            "ask questions interactively. For an unsupported question return needs_input "
            "with missing_inputs and null data. completed requires a plan, empty missing_inputs, "
            "null failure; failed requires typed failure and null data. Never emit SQL."
        ),
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "max_turns": 3,
        "response_schema": ENVELOPE_SCHEMA,
        "metadata": {"parent_tool_call_id": authority.get("tool_call_id")},
    }
    if not nested:
        request.pop("parent_job_id")
        request.pop("root_job_id")
    client = client_for(scope, "text_to_sql", profile)
    try:
        result = client.complete(request)
    finally:
        try:
            if client.last_job_id:
                record_job_usage(
                    client,
                    scope,
                    "text_to_sql",
                    request["model"],
                    client.last_job_id,
                    source="metadata_child" if nested else "mcp",
                )
        finally:
            client.close()
    envelope = result.structured
    if not isinstance(envelope, dict) or envelope.get("outcome") != "completed":
        raise ExecutionError("metadata_invalid_outcome")
    plan = envelope["data"]
    from jsonschema import validate

    validate(plan, PLAN_SCHEMA)
    response = (
        get_supabase_thread_safe()
        .rpc(
            "tsukai_scoped_metadata",
            {
                "p_owner_id": scope.owner_id,
                "p_folder_ids": list(scope.folder_ids),
                "p_operation": plan["operation"],
                "p_source_type": plan["source_type"],
                "p_filename": plan["filename"],
                "p_created_after": plan["created_after"],
                "p_created_before": plan["created_before"],
            },
        )
        .execute()
        .data
    )
    return json.dumps(response, ensure_ascii=False)
