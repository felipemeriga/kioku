"""Read-only repository journal and current-learning views for the web UI."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from db.client import get_supabase_thread_safe
from services.agent_journal import read_journal

router = APIRouter(prefix="/api/folders", tags=["learnings"])


def _repo(sb, folder_id: str, user_id: str) -> None:
    rows = (
        sb.table("folders")
        .select("id,kind")
        .eq("id", folder_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or rows[0].get("kind") != "repo":
        raise HTTPException(status_code=404, detail="Repository not found")


@router.get("/{folder_id}/learning-days")
def learning_days(
    folder_id: str, year: int = Query(ge=2000, le=2100), user_id: str = Depends(get_current_user)
):
    sb = get_supabase_thread_safe()
    _repo(sb, folder_id, user_id)
    rows = (
        sb.table("agent_journal_days")
        .select("journal_date,revision,entry_count,agents,first_entry_at,last_entry_at")
        .eq("user_id", user_id)
        .eq("folder_id", folder_id)
        .gte("journal_date", f"{year}-01-01")
        .lte("journal_date", f"{year}-12-31")
        .order("journal_date", desc=True)
        .limit(366)
        .execute()
        .data
        or []
    )
    return {"days": rows}


@router.get("/{folder_id}/learning-days/{journal_date}")
def learning_day(folder_id: str, journal_date: str, user_id: str = Depends(get_current_user)):
    try:
        date.fromisoformat(journal_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid date") from exc
    sb = get_supabase_thread_safe()
    _repo(sb, folder_id, user_id)
    return read_journal(sb, user_id, folder_id, journal_date)


@router.get("/{folder_id}/learnings")
def learnings(folder_id: str, user_id: str = Depends(get_current_user)):
    sb = get_supabase_thread_safe()
    _repo(sb, folder_id, user_id)
    rows = (
        sb.table("repo_learnings")
        .select("id,topic_key,statement,status,source_entries,git_sha,reviewed_head_sha,updated_at")
        .eq("user_id", user_id)
        .eq("folder_id", folder_id)
        .neq("status", "retired")
        .order("updated_at", desc=True)
        .limit(200)
        .execute()
        .data
        or []
    )
    return {"learnings": rows}
