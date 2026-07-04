"""Folder CRUD + summary endpoints for organizing documents."""

import os

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from services.folder_summary.repo import (
    get_folder,
    get_latest_summary,
    get_summary_history,
)

router = APIRouter(prefix="/api/folders")


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


class CreateFolderRequest(BaseModel):
    name: str
    parent_id: str | None = None


class RenameFolderRequest(BaseModel):
    name: str


@router.get("")
async def list_folders(
    parent_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """List folders for a given parent (or root if parent_id is None)."""
    sb = get_supabase()
    query = sb.table("folders").select("*").eq("user_id", user_id)

    if parent_id:
        query = query.eq("parent_id", parent_id)
    else:
        query = query.is_("parent_id", "null")

    result = query.order("name").execute()
    return result.data


@router.post("")
async def create_folder(
    body: CreateFolderRequest,
    user_id: str = Depends(get_current_user),
):
    """Create a new folder."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Folder name cannot be empty")

    sb = get_supabase()

    # Verify parent folder belongs to user if specified
    if body.parent_id:
        parent = (
            sb.table("folders")
            .select("id")
            .eq("id", body.parent_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not parent.data:
            raise HTTPException(status_code=404, detail="Parent folder not found")

    result = (
        sb.table("folders")
        .insert(
            {
                "name": body.name.strip(),
                "parent_id": body.parent_id,
                "user_id": user_id,
            }
        )
        .execute()
    )
    return result.data[0]


@router.patch("/{folder_id}")
async def rename_folder(
    folder_id: str,
    body: RenameFolderRequest,
    user_id: str = Depends(get_current_user),
):
    """Rename a folder."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Folder name cannot be empty")

    sb = get_supabase()
    result = (
        sb.table("folders")
        .update({"name": body.name.strip()})
        .eq("id", folder_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Folder not found")
    return result.data[0]


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a folder and all subfolders (cascade). Documents get folder_id set to null."""
    sb = get_supabase()
    sb.table("folders").delete().eq("id", folder_id).eq("user_id", user_id).execute()
    return {"ok": True}


class RegenerateSummaryRequest(BaseModel):
    mode: str = "auto"  # auto | full | delta


@router.get("/{folder_id}/summary")
async def get_folder_summary(
    folder_id: str,
    user_id: str = Depends(get_current_user),
):
    """Latest folder summary + minimal metadata for the panel."""
    sb = get_supabase()
    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    latest = get_latest_summary(sb, folder_id, user_id)
    return {
        "folder": folder,
        "summary": latest,
    }


@router.get("/{folder_id}/summary/history")
async def get_folder_summary_history(
    folder_id: str,
    limit: int = 10,
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase()
    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return get_summary_history(sb, folder_id, user_id, limit=limit)


@router.post("/{folder_id}/summary/regenerate")
async def regenerate_folder_summary(
    folder_id: str,
    body: RegenerateSummaryRequest,
    user_id: str = Depends(get_current_user),
):
    """Enqueue a summarize_folder_task and return the arq job id."""
    if body.mode not in {"auto", "full", "delta"}:
        raise HTTPException(status_code=400, detail="mode must be auto|full|delta")

    sb = get_supabase()
    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "summarize_folder_task",
            {
                "folder_id": folder_id,
                "user_id": user_id,
                "mode": body.mode,
                "trigger": "manual",
            },
        )
    finally:
        await pool.close()

    return {"ok": True, "job_id": job.job_id if job else None, "mode": body.mode}


@router.get("/{folder_id}/breadcrumbs")
async def get_breadcrumbs(
    folder_id: str,
    user_id: str = Depends(get_current_user),
):
    """Return the breadcrumb path from root to the given folder."""
    sb = get_supabase()
    breadcrumbs = []
    current_id: str | None = folder_id

    while current_id:
        result = (
            sb.table("folders")
            .select("id, name, parent_id")
            .eq("id", current_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            break
        folder = result.data[0]
        breadcrumbs.append({"id": folder["id"], "name": folder["name"]})
        current_id = folder.get("parent_id")

    breadcrumbs.reverse()
    return breadcrumbs
