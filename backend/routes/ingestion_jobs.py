"""HTTP routes for polling ingestion progress."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user
from db.client import get_supabase
from routes._validation import require_uuid

router = APIRouter(prefix="/api/ingestion-jobs", tags=["ingestion"])


@router.get("/{job_id}")
async def get_job(job_id: str, user_id: str = Depends(get_current_user)):
    require_uuid(job_id, "Job not found")
    sb = get_supabase()
    rows = (
        sb.table("ingestion_jobs")
        .select("*")
        .eq("id", job_id)
        .eq("user_id", user_id)
        .execute()
        .data
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Job not found")
    return rows[0]


@router.get("")
async def list_active_jobs(user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    rows = (
        sb.table("ingestion_jobs")
        .select("*")
        .eq("user_id", user_id)
        .in_("status", ["queued", "running"])
        .execute()
        .data
    ) or []
    return rows
