from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from routes._validation import require_uuid
from services.rag import stream_rag_response
from services.scope import validate_scope_folder

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    conversation_id: str
    content: str
    # Two independent knobs: which model, and the mode.
    # mode: plain (classic one-shot RAG) | agentic (tool loop) | deep (+ thinking)
    model: Literal["haiku", "sonnet"] = "sonnet"
    mode: Literal["plain", "agentic", "deep"] = "deep"
    # When true, the stream ends with a debug frame (reasoning, tool calls,
    # retrieved chunks + rerank scores) for the UI's Inspect card.
    debug: bool = False
    # RAG scope: restrict retrieval to a folder subtree and/or one document.
    scope_folder_id: str | None = None
    scope_filename: str | None = None


@router.post("/chat")
async def chat(request: ChatRequest, user_id: str = Depends(get_current_user)):
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
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")
