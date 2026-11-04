from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase_thread_safe as get_supabase
from routes._validation import require_uuid

router = APIRouter(prefix="/api/conversations")


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.get("")
def list_conversations(user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("id, title, created_at, updated_at")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .execute()
    )
    return result.data


@router.post("")
def create_conversation(user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    result = sb.table("conversations").insert({"user_id": user_id}).execute()
    return result.data[0]


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, user_id: str = Depends(get_current_user)):
    require_uuid(conversation_id, "Conversation not found")
    sb = get_supabase()
    conv = (
        sb.table("conversations")
        .select("id, title, created_at, updated_at")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = (
        sb.table("messages")
        .select("id, role, content, created_at, debug, citations")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    active_execution = None
    from services.ai.registry import engine_for

    if any(engine_for(op, user_id) == "tsukai" for op in ("rag_agent", "rag_agent_sonnet")):
        from services.ai.chat import turn_scope

        turns = (
            sb.table("tsukai_chat_turns")
            .select("*")
            .eq("owner_id", user_id)
            .eq("conversation_id", conversation_id)
            .not_.is_("job_id", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        missing_assistant = False
        if turns:
            turn = turns[0]
            expected_ids = {turn.get("user_message_id"), turn.get("assistant_message_id")} - {None}
            if not expected_ids.issubset({row["id"] for row in messages.data}):
                # Admission or publication may commit between messages and turn reads.
                messages = (
                    sb.table("messages")
                    .select("id, role, content, created_at, debug, citations")
                    .eq("conversation_id", conversation_id)
                    .order("created_at")
                    .execute()
                )
            missing_assistant = bool(turn.get("assistant_message_id")) and (
                turn["assistant_message_id"] not in {row["id"] for row in messages.data}
            )
        if (
            turns
            and turns[0].get("job_id")
            and (
                missing_assistant
                or (
                    not turns[0].get("assistant_message_id")
                    and turns[0]["state"]
                    in {"prepared", "submitted", "failed", "cancelled", "uncertain"}
                )
            )
        ):
            turn = turns[0]
            try:
                turn_scope(turn)
            except HTTPException as exc:
                if exc.status_code not in (403, 404):
                    raise
            else:
                intent = turn["request"]["metadata"]["intent"]
                active_execution = {
                    "state": turn["state"],
                    "user_message_id": turn.get("user_message_id"),
                    "scope_folder_id": intent.get("scope_folder_id"),
                    "scope_filename": intent.get("scope_filename"),
                    "turn_id": turn["id"],
                    "job_id": turn["job_id"],
                    "conversation_id": conversation_id,
                    "model": intent["model"],
                    "mode": intent["mode"],
                }
    visible_messages = messages.data
    duplicate_candidates = {
        earlier["id"]
        for earlier, later in zip(visible_messages, visible_messages[1:])
        if earlier["role"] == later["role"] == "user" and earlier["content"] == later["content"]
    }
    if duplicate_candidates:
        # Keep the audit rows, but don't show an unstarted rejected request
        # twice when the user retries it. Accepted/uncertain jobs stay visible.
        rejected = (
            sb.table("tsukai_chat_turns")
            .select("user_message_id")
            .eq("owner_id", user_id)
            .eq("conversation_id", conversation_id)
            .eq("state", "failed")
            .eq("error_code", "conversation_policy_changed")
            .is_("job_id", "null")
            .in_("user_message_id", list(duplicate_candidates))
            .execute()
            .data
            or []
        )
        rejected_ids = {turn["user_message_id"] for turn in rejected}
        visible_messages = [m for m in visible_messages if m["id"] not in rejected_ids]
    from services.citations import enrich_source_urls

    enrich_source_urls(
        sb,
        user_id,
        [citation for message in visible_messages for citation in message.get("citations") or []],
    )
    return {**conv.data[0], "messages": visible_messages, "active_execution": active_execution}


@router.patch("/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    body: RenameConversationRequest,
    user_id: str = Depends(get_current_user),
):
    """Rename a conversation. Trims whitespace; refuses an empty title."""
    require_uuid(conversation_id, "Conversation not found")
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .update({"title": title})
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result.data[0]


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str, user_id: str = Depends(get_current_user)):
    require_uuid(conversation_id, "Conversation not found")
    sb = get_supabase()
    sb.table("conversations").delete().eq("id", conversation_id).eq("user_id", user_id).execute()
    return {"ok": True}
