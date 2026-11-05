"""Read-only repository journal and current-learning views for the web UI."""

from calendar import monthrange
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from postgrest.exceptions import APIError
from storage3.exceptions import StorageApiError

from auth import get_current_user
from db.client import get_supabase_thread_safe
from services.agent_journal import (
    local_journal_day,
    local_journal_days_indexed,
    read_journal,
    read_journals_in_range,
)

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
    folder_id: str,
    year: int = Query(ge=2000, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    timezone: str | None = None,
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase_thread_safe()
    _repo(sb, folder_id, user_id)
    if timezone is not None:
        if month is None:
            raise HTTPException(status_code=422, detail="Month is required with timezone")
        try:
            tz = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid timezone") from exc
        first = date(year, month, 1)
        last = date(year, month, monthrange(year, month)[1])
        rows = (
            sb.table("agent_journal_days")
            .select(
                "journal_date,storage_path,content_sha256,revision,entry_count,agents,first_entry_at,last_entry_at"
            )
            .eq("user_id", user_id)
            .eq("folder_id", folder_id)
            .gte("journal_date", (first - timedelta(days=2)).isoformat())
            .lte("journal_date", (last + timedelta(days=2)).isoformat())
            .order("journal_date")
            .limit(40)
            .execute()
            .data
            or []
        )
        return {"days": local_journal_days_indexed(sb, rows, tz, year, month)}
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
def learning_day(
    folder_id: str,
    journal_date: str,
    timezone: str | None = None,
    user_id: str = Depends(get_current_user),
):
    try:
        target = date.fromisoformat(journal_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid date") from exc
    sb = get_supabase_thread_safe()
    _repo(sb, folder_id, user_id)
    if timezone is not None:
        try:
            tz = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Invalid timezone") from exc
        try:
            journals = read_journals_in_range(sb, user_id, folder_id, target, target, tz)
        except StorageApiError as exc:
            raise HTTPException(
                status_code=503, detail="Journal storage is temporarily unavailable"
            ) from exc
        return local_journal_day(journals, tz, target)
    try:
        return read_journal(sb, user_id, folder_id, journal_date)
    except StorageApiError as exc:
        raise HTTPException(
            status_code=503, detail="Journal storage is temporarily unavailable"
        ) from exc


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


@router.get("/{folder_id}/history-search")
def history_search(
    folder_id: str,
    q: str = Query(default="", max_length=160),
    mode: str = "words",
    fields: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    agent: str | None = None,
    session_id: str | None = Query(default=None, max_length=256),
    timezone: str = "UTC",
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    user_id: str = Depends(get_current_user),
):
    from services.history_search import search_history

    sb = get_supabase_thread_safe()
    _repo(sb, folder_id, user_id)
    try:
        return search_history(
            sb,
            user_id,
            folder_id,
            q=q,
            mode=mode,
            fields=fields,
            date_from=date_from,
            date_to=date_to,
            agent=agent,
            session_id=session_id,
            timezone=timezone,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except APIError as exc:
        if exc.code in {"2201B", "2201C"}:
            raise HTTPException(status_code=422, detail="Invalid regular expression") from exc
        if exc.code == "57014":
            raise HTTPException(
                status_code=422, detail="Search exceeded its time limit; narrow the filters"
            ) from exc
        raise


@router.post("/{folder_id}/history-search/backfill")
def history_search_backfill(
    folder_id: str,
    limit: int = Query(default=10, ge=1, le=20),
    user_id: str = Depends(get_current_user),
):
    from services.history_search import backfill_search

    sb = get_supabase_thread_safe()
    _repo(sb, folder_id, user_id)
    try:
        return backfill_search(sb, user_id, folder_id, limit)
    except StorageApiError as exc:
        raise HTTPException(
            status_code=503, detail="Journal storage is temporarily unavailable"
        ) from exc
