"""HTTP routes for managing Notion sync configs."""

from __future__ import annotations

import logging

from arq import create_pool
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from services.crypto import encrypt_secret
from services.notion_sync.client import NotionClient
from services.queue.jobs import create_job, get_active_job, is_job_stale, mark_failed
from services.queue.settings import _redis_settings

router = APIRouter(prefix="/api/notion", tags=["notion"])
log = logging.getLogger(__name__)


def _is_uuid(s: str) -> bool:
    """A config_id that isn't a well-formed UUID can never match a real config.
    Guard before it reaches the uuid DB column, where Postgres raises 22P02 and
    surfaces as an uncaught 500 (returns 404 for a malformed id, like a
    well-formed-but-nonexistent one)."""
    import uuid as _uuid

    try:
        _uuid.UUID(str(s))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class ConnectRequest(BaseModel):
    root_folder_id: str
    notion_page_id: str
    notion_page_title: str
    integration_token: str
    fast_poll_interval_min: int = 5


class ConfigResponse(BaseModel):
    id: str
    root_folder_id: str
    notion_page_id: str
    notion_page_title: str | None
    fast_poll_interval_min: int
    last_fast_sync_at: str | None
    last_full_sync_at: str | None
    last_error: str | None


class NotionPageOption(BaseModel):
    id: str
    title: str


@router.get("/configs", response_model=list[ConfigResponse])
async def list_configs(user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    rows = (
        sb.table("notion_sync_configs")
        .select(
            "id, root_folder_id, notion_page_id, notion_page_title, "
            "fast_poll_interval_min, last_fast_sync_at, last_full_sync_at, last_error"
        )
        .eq("user_id", user_id)
        .execute()
        .data
    ) or []
    return rows


@router.post("/configs", response_model=ConfigResponse)
async def connect(body: ConnectRequest, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    encrypted = encrypt_secret(body.integration_token)
    try:
        inserted = (
            sb.table("notion_sync_configs")
            .insert(
                {
                    "user_id": user_id,
                    "root_folder_id": body.root_folder_id,
                    "notion_page_id": body.notion_page_id,
                    "notion_page_title": body.notion_page_title,
                    "integration_token_encrypted": encrypted,
                    "fast_poll_interval_min": body.fast_poll_interval_min,
                }
            )
            .execute()
            .data[0]
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Config exists or invalid: {exc}") from exc

    # Kick off the first sync immediately so the folder starts populating right
    # after connecting — instead of waiting for the scheduler's next tick. A
    # full reconcile pulls the whole page tree. Best effort: if the queue is
    # down, the periodic scheduler still picks it up (last_full_sync_at is None
    # → immediately due).
    try:
        await _enqueue_sync(inserted["id"], user_id, full_reconcile=True)
    except Exception as exc:  # noqa: BLE001 — never fail connect on a queue hiccup
        log.warning("initial notion sync enqueue failed for %s: %s", inserted["id"], exc)

    return inserted


@router.delete("/configs/{config_id}")
async def disconnect(
    config_id: str,
    delete_docs: bool = False,
    user_id: str = Depends(get_current_user),
):
    if not _is_uuid(config_id):
        raise HTTPException(status_code=404, detail="Config not found")
    sb = get_supabase()
    cfg_rows = (
        sb.table("notion_sync_configs")
        .select("*")
        .eq("id", config_id)
        .eq("user_id", user_id)
        .execute()
        .data
    )
    if not cfg_rows:
        raise HTTPException(status_code=404, detail="Config not found")
    cfg = cfg_rows[0]

    if delete_docs:
        (
            sb.table("documents")
            .delete()
            .eq("user_id", user_id)
            .eq("root_folder_id", cfg["root_folder_id"])
            .eq("source_type", "notion")
            .execute()
        )

    sb.table("notion_sync_configs").delete().eq("id", config_id).eq("user_id", user_id).execute()
    return {"deleted": True, "docs_deleted": delete_docs}


async def _enqueue_sync(config_id: str, user_id: str, full_reconcile: bool) -> dict:
    if not _is_uuid(config_id):
        raise HTTPException(status_code=404, detail="Config not found")
    sb = get_supabase()
    rows = (
        sb.table("notion_sync_configs")
        .select("*")
        .eq("id", config_id)
        .eq("user_id", user_id)
        .execute()
        .data
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Config not found")
    cfg = rows[0]

    existing = get_active_job(sb, kind="notion_sync", source_ref=config_id)
    if existing and is_job_stale(existing):
        # A zombie from a prior worker outage — reap it so this sync can run
        # instead of being blocked by a job that will never finish.
        mark_failed(sb, job_id=existing["id"], error="stale: superseded by a new sync")
        existing = None
    if existing:
        return {"job_id": existing["id"], "already_running": True}

    job_id = create_job(
        sb,
        user_id=user_id,
        kind="notion_sync",
        source_ref=config_id,
        root_folder_id=cfg["root_folder_id"],
    )
    pool = await create_pool(_redis_settings())
    try:
        # Unique _job_id per enqueue (the fresh DB job_id). A deterministic id
        # would be deduped by arq against a PREVIOUS run of the same config for
        # up to keep_result (24h) — creating a DB row but never enqueuing a real
        # arq job, i.e. a zombie stuck at "queued". Concurrency is already
        # prevented by the get_active_job check above.
        await pool.enqueue_job(
            "notion_sync_task",
            {
                "job_id": job_id,
                "config_id": config_id,
                "full_reconcile": full_reconcile,
            },
            _job_id=f"notion_sync:{job_id}",
        )
    finally:
        await pool.close()

    return {"job_id": job_id, "already_running": False}


@router.post("/configs/{config_id}/sync")
async def sync_now(config_id: str, user_id: str = Depends(get_current_user)):
    return await _enqueue_sync(config_id, user_id, full_reconcile=False)


@router.post("/configs/{config_id}/reconcile")
async def reconcile_now(config_id: str, user_id: str = Depends(get_current_user)):
    return await _enqueue_sync(config_id, user_id, full_reconcile=True)


@router.get("/pages", response_model=list[NotionPageOption])
async def list_pages(
    integration_token: str,
    query: str = "",
    user_id: str = Depends(get_current_user),  # noqa: ARG001 — enforces auth
):
    """Proxy Notion search so the frontend can populate a page picker."""
    try:
        client = NotionClient(integration_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Notion token: {exc}") from exc

    results: list[NotionPageOption] = []
    for page in client.iter_pages_edited_since(since=None):
        if query and query.lower() not in page.title.lower():
            continue
        results.append(NotionPageOption(id=page.page_id, title=page.title))
        if len(results) >= 50:
            break
    return results
