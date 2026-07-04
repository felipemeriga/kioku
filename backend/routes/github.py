"""GitHub integration routes — connect/disconnect + on-demand sync."""

from __future__ import annotations

import logging
import os

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase
from services.crypto import encrypt_secret
from services.github_sync import GitHubClient, parse_repo_url

router = APIRouter(prefix="/api/github")
log = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


def _validate_folder(sb, folder_id: str, user_id: str) -> None:
    """Only checks ownership. Both root and sub-folders can host GitHub configs."""
    row = (
        sb.table("folders")
        .select("id")
        .eq("id", folder_id).eq("user_id", user_id)
        .limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")


class ConnectGitHubRequest(BaseModel):
    root_folder_id: str
    repo_url: str
    token: str | None = None
    since_days: int = Field(default=14, ge=1, le=365)


@router.get("/configs")
async def list_configs(user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    rows = (
        sb.table("github_sync_configs")
        .select("id, root_folder_id, repo_owner, repo_name, since_days, last_synced_at, last_error, created_at, updated_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute().data
    )
    folder_ids = [r["root_folder_id"] for r in rows]
    name_by_id = {}
    if folder_ids:
        fr = sb.table("folders").select("id, name").in_("id", folder_ids).execute().data
        name_by_id = {f["id"]: f["name"] for f in fr}
    for r in rows:
        r["root_folder_name"] = name_by_id.get(r["root_folder_id"], "?")
        r["has_token"] = True  # we don't leak the token but expose whether one is stored
    return rows


@router.post("/connect")
async def connect(body: ConnectGitHubRequest, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    _validate_folder(sb, body.root_folder_id, user_id)

    try:
        owner, repo = parse_repo_url(body.repo_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Verify the token + repo access.
    with GitHubClient(owner=owner, repo=repo, token=body.token or None) as gh:
        ok, err = gh.ping()
    if not ok:
        raise HTTPException(status_code=400, detail=f"GitHub check failed: {err}")

    payload = {
        "user_id": user_id,
        "root_folder_id": body.root_folder_id,
        "repo_owner": owner,
        "repo_name": repo,
        "token_encrypted": encrypt_secret(body.token) if body.token else None,
        "since_days": body.since_days,
        "last_error": None,
    }
    row = (
        sb.table("github_sync_configs")
        .upsert(payload, on_conflict="user_id,root_folder_id")
        .execute()
        .data
    )
    return row[0] if row else {"ok": True}


@router.delete("/configs/{config_id}")
async def disconnect(
    config_id: str,
    delete_docs: bool = False,
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase()
    # Find folder + owner before delete for optional doc cleanup.
    row = (
        sb.table("github_sync_configs").select("*")
        .eq("id", config_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    folder_id = row[0]["root_folder_id"]
    sb.table("github_sync_configs").delete().eq("id", config_id).eq("user_id", user_id).execute()
    if delete_docs:
        sb.table("documents").delete().eq("user_id", user_id).eq("folder_id", folder_id).in_(
            "source_type", ["github_commit", "github_pr", "github_issue"],
        ).execute()
    return {"ok": True}


class ListReposRequest(BaseModel):
    token: str = Field(min_length=8)


@router.post("/repos")
async def list_repos(body: ListReposRequest, user_id: str = Depends(get_current_user)):
    """Fetch the user's accessible repos (sorted by most recently pushed)
    so the connect dialog can render them as a picker instead of asking the
    user to paste a URL. Token is used only for this request and NOT persisted.
    """
    from services.github_sync import GitHubClient
    try:
        repos = GitHubClient.list_user_repos(body.token, max_items=200)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"GitHub rejected the token: {e}")
    return repos


@router.post("/configs/{config_id}/sync")
async def sync_now(config_id: str, user_id: str = Depends(get_current_user)):
    """Enqueue a github_sync_task."""
    sb = get_supabase()
    row = (
        sb.table("github_sync_configs").select("id, root_folder_id")
        .eq("id", config_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    pool = await create_pool(_redis_settings())
    try:
        job = await pool.enqueue_job(
            "github_sync_task",
            {"config_id": config_id, "user_id": user_id},
        )
    finally:
        await pool.close()
    return {"ok": True, "job_id": job.job_id if job else None}
