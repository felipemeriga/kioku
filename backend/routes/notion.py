"""HTTP routes for managing Notion sync configs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from services.crypto import decrypt_secret, encrypt_secret
from services.notion_sync.client import NotionClient
from services.notion_sync.sync_engine import fast_poll, full_reconciliation

router = APIRouter(prefix="/api/notion", tags=["notion"])


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
    return inserted


@router.delete("/configs/{config_id}")
async def disconnect(
    config_id: str,
    delete_docs: bool = False,
    user_id: str = Depends(get_current_user),
):
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


@router.post("/configs/{config_id}/sync")
async def sync_now(config_id: str, user_id: str = Depends(get_current_user)):
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

    client = NotionClient(decrypt_secret(cfg["integration_token_encrypted"]))
    fast_result = fast_poll(sb, client, cfg)
    full_result = full_reconciliation(sb, client, cfg)
    return {
        "fast": fast_result,
        "full": full_result,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


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
