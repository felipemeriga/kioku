"""Tool-disabled reserved child generates a typed plan; SQL remains parameterized."""

import json
import logging
from uuid import uuid4

from db.client import get_supabase_thread_safe
from services.ai.client import ExecutionError
from services.ai.consumption import consume_result
from services.ai.contracts import completion_envelope
from services.ai.evidence import save_trace
from services.ai.facade import client_for
from services.ai.scope import ExecutionScope

logger = logging.getLogger(__name__)

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
ENVELOPE_SCHEMA = completion_envelope(PLAN_SCHEMA)


def metadata_query(question: str, authority: dict, *, on_consumption=None) -> str:
    nested = bool(authority.get("job_id"))
    profile = "metadata_child" if nested else "completion"
    scope = ExecutionScope(
        authority["owner_id"],
        tuple(authority["folder_ids"]),
        caller="backend" if nested else "mcp",
        parent_job_id=authority.get("job_id"),
        root_job_id=authority.get("job_id"),
        ai_depth=1 if nested else 0,
        conversation_id=authority.get("conversation_id"),
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
    if nested:
        request.update({"parent_job_id": scope.parent_job_id, "root_job_id": scope.root_job_id})
    client = client_for(scope, "text_to_sql", profile)
    result, error, output = None, None, ""
    try:
        result = client.complete(request)
        envelope = result.structured
        from jsonschema import validate

        validate(envelope, ENVELOPE_SCHEMA)
        if not isinstance(envelope, dict) or envelope.get("outcome") != "completed":
            raise ExecutionError("metadata_invalid_outcome")
        plan = envelope["data"]
        validate(plan, PLAN_SCHEMA)
        fixed_filename = authority.get("scope_filename")
        if fixed_filename and plan["filename"] not in (None, fixed_filename):
            raise ExecutionError(
                "metadata_scope_conflict", "query attempted to leave the selected file"
            )
        response = (
            get_supabase_thread_safe()
            .rpc(
                "tsukai_scoped_metadata",
                {
                    "p_owner_id": scope.owner_id,
                    "p_folder_ids": list(scope.folder_ids),
                    "p_operation": plan["operation"],
                    "p_source_type": plan["source_type"],
                    "p_filename": fixed_filename or plan["filename"],
                    "p_created_after": plan["created_after"],
                    "p_created_before": plan["created_before"],
                },
            )
            .execute()
            .data
        )
        output = json.dumps(response, ensure_ascii=False)
        return output
    except Exception as exc:
        error = exc
        raise
    finally:
        job_id = result.job_id if result else client.last_job_id
        client.close()
        terminal_failure = isinstance(error, ExecutionError) and error.code in {
            "needs_input",
            "failed",
            "interaction_required",
            "metadata_invalid_outcome",
        }
        if job_id:
            consumed = {
                "scope": scope,
                "operation": "text_to_sql",
                "profile": profile,
                "job_id": job_id,
                "model": request["model"],
                "outcome": "completed" if error is None else getattr(error, "code", "failed"),
                "acknowledge_completed": result is not None or terminal_failure,
            }
            try:
                if on_consumption:
                    # The harness records its final exact tool artifact first.
                    on_consumption(consumed)
                else:
                    artifact = save_trace(
                        scope.owner_id,
                        job_id,
                        (result.attempt_id or "unknown") if result else "unknown",
                        list(scope.folder_ids),
                        {
                            "name": "query_documents_metadata",
                            "input": {"question": question},
                            "status": "completed" if error is None else "failed",
                            "effective_scope": {
                                "user_id": scope.owner_id,
                                "folder_ids": list(scope.folder_ids),
                                "filename": authority.get("scope_filename"),
                            },
                        },
                        output if error is None else "Scoped metadata query did not complete",
                    )
                    consume_metadata(consumed, artifact)
            except Exception:
                if error is None:
                    raise
                logger.warning("metadata failure accounting could not be persisted")


def consume_metadata(consumed: dict, artifact_id: str):
    consume_result(
        consumed["scope"],
        consumed["operation"],
        consumed["profile"],
        consumed["job_id"],
        "metadata",
        artifact_id,
        {
            "model": consumed["model"],
            "outcome": consumed["outcome"],
            "artifact_id": artifact_id,
            "acknowledge_completed": consumed["acknowledge_completed"],
        },
    )
