"""Context CRUD endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from db.client import get_supabase
from routes._validation import require_uuid

router = APIRouter(prefix="/api/context")


@router.get("")
async def list_context(
    root_folder_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """List active context entries, optionally filtered by scope."""
    if root_folder_id:
        require_uuid(root_folder_id, "Folder not found")
    sb = get_supabase()
    query = (
        sb.table("context")
        .select("*")
        .eq("user_id", user_id)
        .gt("expires_at", datetime.now(timezone.utc).isoformat())
    )
    if root_folder_id:
        query = query.eq("root_folder_id", root_folder_id)
    result = query.order("created_at", desc=True).execute()
    return result.data


@router.delete("/clear")
async def clear_context(
    root_folder_id: str,
    user_id: str = Depends(get_current_user),
):
    """Clear all context entries for a scope."""
    require_uuid(root_folder_id, "Folder not found")
    sb = get_supabase()
    sb.table("context").delete().eq("user_id", user_id).eq(
        "root_folder_id", root_folder_id
    ).execute()
    return {"ok": True}


@router.delete("/{context_id}")
async def delete_context_entry(
    context_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a context entry."""
    require_uuid(context_id, "Context entry not found")
    sb = get_supabase()
    result = sb.table("context").delete().eq("id", context_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Context entry not found")
    return {"ok": True}
