"""Owner-scoped, read-only report revisions and explicit report timezone settings."""

from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user
from db.client import get_supabase_thread_safe
from routes.learnings import _repo

router = APIRouter(prefix="/api/folders", tags=["reports"])
SUMMARY = "id,kind,period_start,period_end,timezone,cutoff,status,revision,generated_at,coverage"


class ReportSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Invalid IANA timezone") from exc
        return value


def report_timezone(sb, user_id, folder_id):
    rows = (
        sb.table("watched_repos")
        .select("report_timezone")
        .eq("user_id", user_id)
        .eq("folder_id", folder_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return (rows[0].get("report_timezone") or "UTC") if rows else "UTC"


@router.get("/{folder_id}/reports")
def reports(
    folder_id: UUID,
    kind: Literal["weekly", "monthly"] = "weekly",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000),
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase_thread_safe()
    fid = str(folder_id)
    _repo(sb, fid, user_id)
    try:
        tz = report_timezone(sb, user_id, fid)
        rows = (
            sb.table("repo_period_reports")
            .select(SUMMARY)
            .eq("user_id", user_id)
            .eq("folder_id", fid)
            .eq("kind", kind)
            .eq("timezone", tz)
            .order("period_start", desc=True)
            .range(offset, offset + limit)
            .execute()
            .data
            or []
        )
        return {"reports": rows[:limit], "has_more": len(rows) > limit, "timezone": tz}
    except APIError as exc:
        raise HTTPException(
            status_code=503, detail="Reports are temporarily unavailable. Try again shortly."
        ) from exc


@router.put("/{folder_id}/report-settings")
def settings(folder_id: UUID, body: ReportSettings, user_id: str = Depends(get_current_user)):
    sb = get_supabase_thread_safe()
    fid = str(folder_id)
    _repo(sb, fid, user_id)
    rows = (
        sb.table("watched_repos")
        .update({"report_timezone": body.timezone})
        .eq("user_id", user_id)
        .eq("folder_id", fid)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(
            status_code=409, detail="Connect this repository to Mihari before configuring reports."
        )
    return {"timezone": body.timezone}


@router.get("/{folder_id}/reports/{report_id}")
def report(
    folder_id: UUID,
    report_id: UUID,
    revision: int | None = Query(default=None, ge=1),
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase_thread_safe()
    fid = str(folder_id)
    _repo(sb, fid, user_id)
    try:
        rows = (
            sb.table("repo_period_reports")
            .select("*")
            .eq("user_id", user_id)
            .eq("folder_id", fid)
            .eq("id", str(report_id))
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Report not found")
        value = rows[0]
        versions = (
            sb.table("repo_period_report_revisions")
            .select("revision,generated_at,cutoff,status")
            .eq("user_id", user_id)
            .eq("report_id", str(report_id))
            .order("revision", desc=True)
            .limit(100)
            .execute()
            .data
            or []
        )
        if revision is not None and revision != value["revision"]:
            prior = (
                sb.table("repo_period_report_revisions")
                .select("*")
                .eq("user_id", user_id)
                .eq("report_id", str(report_id))
                .eq("revision", revision)
                .limit(1)
                .execute()
                .data
                or []
            )
            if not prior:
                raise HTTPException(status_code=404, detail="Report revision not found")
            value = {**value, **prior[0], "id": str(report_id)}
        return {"report": value, "revisions": versions}
    except APIError as exc:
        raise HTTPException(
            status_code=503, detail="Could not load this report. Try again shortly."
        ) from exc
