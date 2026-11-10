from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase_thread_safe as get_supabase
from routes._validation import require_uuid
from services.ai.registry import engine_for
from services.rag import stream_rag_response
from services.scope import validate_scope_folder

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    conversation_id: str
    content: str
    turn_id: str | None = None
    rebuild_from_committed_history: bool = False
    # Model, retrieval mode and reasoning effort are independent.
    # Legacy clients that explicitly send Deep without an effort retain Deep behavior.
    model: str = Field(default="haiku", min_length=1, max_length=160)
    mode: Literal["plain", "agentic", "deep"] = "agentic"
    reasoning_effort: Literal["low", "medium", "high"] = "low"
    # When true, the stream ends with a debug frame (reasoning, tool calls,
    # retrieved chunks + rerank scores) for the UI's Inspect card.
    debug: bool = False
    # RAG scope: restrict retrieval to a folder subtree and/or one document.
    scope_folder_id: str | None = None
    scope_filename: str | None = None
    timezone: str = Field(default="UTC", max_length=64)


@router.get("/chat/models")
def available_chat_models(user_id: str = Depends(get_current_user)):
    from services.ai.models import chat_models

    return chat_models(user_id)


@router.post("/chat")
def chat(request: ChatRequest, user_id: str = Depends(get_current_user)):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(request.timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise HTTPException(422, "Invalid timezone") from None
    explicit_effort = "reasoning_effort" in request.model_fields_set
    native_effort = request.reasoning_effort
    if not explicit_effort and request.mode == "deep":
        native_effort = "high"
    # Validate before opening the stream: a malformed conversation_id reaches
    # the uuid column in stream_rag_response and raises 22P02, which crashes the
    # generator (client gets a silent empty stream + a server-side traceback).
    require_uuid(request.conversation_id, "Conversation not found")
    # Ownership gate: the conversation must belong to the caller. Without this,
    # a client could pass another user's conversation_id and have
    # stream_rag_response read their history, inject messages, and save replies
    # into it (messages carry no user_id — ownership lives on the conversation).
    sb = get_supabase()
    owns = (
        sb.table("conversations")
        .select("id")
        .eq("id", request.conversation_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    if not owns:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if request.scope_folder_id:
        require_uuid(request.scope_folder_id, "Scope folder not found")
        validate_scope_folder(request.scope_folder_id, user_id)

    from services.ai.models import chat_operation, resolve_native_model

    operation = chat_operation(request.model, user_id)
    if engine_for(operation, user_id) == "tsukai":
        from services.ai.chat import prepare_turn, stream_preparing_turn

        if not request.turn_id:
            raise HTTPException(422, "Native chat requires a stable turn_id")
        require_uuid(request.turn_id, "Invalid turn identifier")
        # Reject unavailable models before the response becomes an SSE stream.
        resolved_model = resolve_native_model(
            request.model, user_id, reasoning_effort=native_effort
        )

        def prepare(on_progress):
            return prepare_turn(
                owner_id=user_id,
                conversation_id=request.conversation_id,
                content=request.content,
                turn_id=request.turn_id,
                model=request.model,
                mode=request.mode,
                rebuild=request.rebuild_from_committed_history,
                folder_id=request.scope_folder_id,
                filename=request.scope_filename,
                user_timezone=request.timezone,
                reasoning_effort=native_effort,
                legacy_effort_retry="reasoning_effort" not in request.model_fields_set,
                model_resolver=lambda _model: resolved_model,
                operation=operation,
                on_progress=on_progress,
            )

        return StreamingResponse(stream_preparing_turn(prepare), media_type="text/event-stream")

    def event_generator():
        yield from stream_rag_response(
            conversation_id=request.conversation_id,
            user_message=request.content,
            user_id=user_id,
            model=request.model,
            mode=request.mode,
            debug=request.debug,
            scope_folder_id=request.scope_folder_id,
            scope_filename=request.scope_filename,
            user_timezone=request.timezone,
            reasoning_effort=request.reasoning_effort if explicit_effort else None,
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/chat/jobs/{job_id}/events")
def native_chat_events(
    job_id: str, after: int = Query(0, ge=0), user_id: str = Depends(get_current_user)
):
    from services.ai.chat import owned_turn, stream_turn

    return StreamingResponse(
        stream_turn(owned_turn(user_id, job_id=job_id), cursor=after),
        media_type="text/event-stream",
    )


@router.post("/chat/jobs/{job_id}/cancel")
def cancel_native_chat(job_id: str, user_id: str = Depends(get_current_user)):
    from services.ai.chat import owned_turn, turn_scope
    from services.ai.facade import client_for

    turn = owned_turn(user_id, job_id=job_id)
    scope, request = turn_scope(turn), turn["request"]
    client = client_for(scope, request["operation"], request["profile"])
    try:
        return client.cancel(job_id)
    finally:
        client.close()


@router.get("/chat/turns/{turn_id}")
def native_chat_turn(turn_id: str, user_id: str = Depends(get_current_user)):
    from services.ai.chat import owned_turn, turn_scope

    require_uuid(turn_id, "Execution not found")
    turn = owned_turn(user_id, turn_id=turn_id)
    turn_scope(turn)
    return {
        key: turn.get(key)
        for key in (
            "id",
            "job_id",
            "conversation_id",
            "state",
            "assistant_message_id",
            "error_code",
        )
    }


@router.get("/chat/jobs/{job_id}/artifacts/{artifact_id}")
def native_tool_artifact(
    job_id: str,
    artifact_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(16384, ge=1, le=65536),
    user_id: str = Depends(get_current_user),
):
    from services.ai.chat import owned_turn, turn_scope

    require_uuid(artifact_id, "Artifact not found")
    turn = owned_turn(user_id, job_id=job_id)
    scope = turn_scope(turn)
    evidence_job = turn["id"] if turn["request"]["profile"] == "completion" else job_id
    rows = (
        get_supabase()
        .table("tsukai_tool_traces")
        .select("*")
        .eq("id", artifact_id)
        .eq("job_id", evidence_job)
        .eq("owner_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or not set(rows[0]["folder_ids"]).issubset(scope.folder_ids):
        raise HTTPException(404, "Artifact not found")
    row = rows[0]
    result = row["result"]
    end = min(offset + limit, len(result))
    return {
        "id": row["id"],
        "trace": row["trace"],
        "result": result[offset:end],
        "offset": offset,
        "next_offset": end if end < len(result) else None,
        "total_characters": len(result),
    }


@router.post("/chat/turns/{turn_id}/cancel")
def cancel_native_turn(turn_id: str, user_id: str = Depends(get_current_user)):
    from services.ai.chat import owned_turn, wake_reconciliation

    require_uuid(turn_id, "Execution not found")
    turn = owned_turn(user_id, turn_id=turn_id)
    if turn["state"] in {"committed", "acknowledged", "failed", "cancelled", "uncertain"}:
        return {"state": turn["state"]}
    get_supabase().table("tsukai_chat_turns").update({"cancel_requested": True}).eq(
        "id", turn_id
    ).eq("owner_id", user_id).execute()
    if turn.get("job_id"):
        cancel_native_chat(turn["job_id"], user_id)
    wake_reconciliation()
    return {"state": "cancel_requested"}
