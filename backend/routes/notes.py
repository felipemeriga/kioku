"""Notes CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from db.client import get_supabase
from routes._validation import require_uuid

router = APIRouter(prefix="/api/notes")


@router.get("")
async def list_notes(
    root_folder_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """List notes, optionally filtered by scope."""
    if root_folder_id:
        require_uuid(root_folder_id, "Folder not found")
    sb = get_supabase()
    query = sb.table("notes").select("*").eq("user_id", user_id)
    if root_folder_id:
        query = query.eq("root_folder_id", root_folder_id)
    result = query.order("created_at", desc=True).execute()
    return result.data


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a note."""
    require_uuid(note_id, "Note not found")
    sb = get_supabase()
    result = sb.table("notes").delete().eq("id", note_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True}
