"""Mem0 integration routes — connect/disconnect + memory proxy.

Every request scopes to the current user via RLS + explicit user_id filters.
Memory reads/writes never leave the Mem0 platform — we're a thin adapter.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase
from services.crypto import encrypt_secret
from services.embeddings import embed_query
from services.mem0_sync import (
    Mem0AppClient,
    MemoryCategory,
    get_client_for_folder,
)
from services.mem0_sync.client import MemoryScope
from services.mem0_sync.fanout import fanout_search

router = APIRouter(prefix="/api/mem0")
log = logging.getLogger(__name__)


def _validate_folder(sb, folder_id: str, user_id: str) -> None:
    """Only checks ownership. Both root and sub-folders can host Mem0 configs."""
    row = (
        sb.table("folders")
        .select("id")
        .eq("id", folder_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Folder not found")


def _load_client(sb, folder_id: str, user_id: str) -> Mem0AppClient:
    client = get_client_for_folder(sb, folder_id, user_id)
    if client is None:
        raise HTTPException(status_code=404, detail="No Mem0 integration for this folder")
    return client


# ─── configs ────────────────────────────────────────────────────────────
class ConnectMem0Request(BaseModel):
    root_folder_id: str
    api_key: str = Field(min_length=8)
    org_id: str | None = None
    project_id: str | None = None


@router.get("/configs")
async def list_configs(user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    rows = (
        sb.table("mem0_sync_configs")
        .select("id, root_folder_id, org_id, project_id, last_verified_at, last_error, created_at, updated_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
        .data
    )
    # Attach folder names for the UI.
    folder_ids = [r["root_folder_id"] for r in rows]
    folder_name_by_id = {}
    if folder_ids:
        fr = (
            sb.table("folders").select("id, name").in_("id", folder_ids)
            .execute().data
        )
        folder_name_by_id = {f["id"]: f["name"] for f in fr}
    for r in rows:
        r["root_folder_name"] = folder_name_by_id.get(r["root_folder_id"], "?")
    return rows


@router.post("/connect")
async def connect(body: ConnectMem0Request, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    _validate_folder(sb, body.root_folder_id, user_id)

    # Verify the API key by pinging Mem0 before persisting.
    ping_config = {
        "id": "probe",
        "api_key_encrypted": encrypt_secret(body.api_key),
        "org_id": body.org_id,
        "project_id": body.project_id,
    }
    probe = Mem0AppClient(
        config=ping_config, user_id=user_id, folder_id=body.root_folder_id
    )
    ok, err = probe.ping()
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Could not authenticate to Mem0: {err}",
        )

    row = (
        sb.table("mem0_sync_configs")
        .upsert(
            {
                "user_id": user_id,
                "root_folder_id": body.root_folder_id,
                "api_key_encrypted": ping_config["api_key_encrypted"],
                "org_id": body.org_id,
                "project_id": body.project_id,
                "last_verified_at": "now()",
                "last_error": None,
            },
            on_conflict="user_id,root_folder_id",
        )
        .execute()
        .data
    )
    return row[0] if row else {"ok": True}


@router.delete("/configs/{config_id}")
async def disconnect(config_id: str, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    sb.table("mem0_sync_configs").delete().eq("id", config_id).eq("user_id", user_id).execute()
    return {"ok": True}


@router.post("/configs/{config_id}/deduplicate")
async def deduplicate(
    config_id: str,
    dry_run: bool = True,
    semantic: bool = True,
    similarity_threshold: float = 0.75,
    user_id: str = Depends(get_current_user),
):
    """Reconcile pre-existing Mem0 duplicates in this folder.

    Two-pass reconciliation:
      - Exact: groups by (scope, category, normalized content).
      - Semantic: for each survivor, uses Mem0 search to find
        rephrases above `similarity_threshold` and merges them.

    dry_run=true returns the plan. semantic=false skips pass 2 (faster,
    stricter). similarity_threshold in [0, 1].
    """
    sb = get_supabase()
    row = (
        sb.table("mem0_sync_configs").select("*")
        .eq("id", config_id).eq("user_id", user_id).limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    client = Mem0AppClient(
        config=row[0], user_id=user_id, folder_id=row[0]["root_folder_id"]
    )
    return client.deduplicate(
        dry_run=dry_run,
        semantic=semantic,
        similarity_threshold=similarity_threshold,
    )


@router.post("/configs/{config_id}/verify")
async def verify_config(config_id: str, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    row = (
        sb.table("mem0_sync_configs")
        .select("*")
        .eq("id", config_id).eq("user_id", user_id)
        .limit(1).execute().data
    )
    if not row:
        raise HTTPException(status_code=404, detail="Config not found")
    probe = Mem0AppClient(config=row[0], user_id=user_id, folder_id=row[0]["root_folder_id"])
    ok, err = probe.ping()
    sb.table("mem0_sync_configs").update({
        "last_verified_at": "now()" if ok else None,
        "last_error": None if ok else err,
    }).eq("id", config_id).execute()
    return {"ok": ok, "error": err}


# ─── memory proxy ────────────────────────────────────────────────────────
class AddMemoryRequest(BaseModel):
    root_folder_id: str
    content: str = Field(min_length=1)
    scope: str = "episodic"
    category: str = MemoryCategory.NOTE
    tags: list[str] | None = None
    written_by: str = "claude-code"


@router.post("/memories")
async def add_memory(body: AddMemoryRequest, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    client = _load_client(sb, body.root_folder_id, user_id)
    result = client.add(
        body.content,
        scope=body.scope,
        category=body.category,
        tags=body.tags,
        written_by=body.written_by,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Mem0 write failed")
    return result


class SearchMemoryRequest(BaseModel):
    root_folder_id: str
    query: str = Field(min_length=1)
    scope: str = "any"       # any | eternal | episodic
    limit: int = 10


@router.post("/search")
async def search_memory(body: SearchMemoryRequest, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    client = _load_client(sb, body.root_folder_id, user_id)
    scope = body.scope if body.scope in (MemoryScope.ETERNAL, MemoryScope.EPISODIC) else MemoryScope.ANY
    hits = client.search(body.query, scope=scope, limit=body.limit)
    return {"hits": hits, "count": len(hits)}


@router.get("/memories/rules")
async def list_rules(root_folder_id: str, user_id: str = Depends(get_current_user)):
    """Eternal preferences for a folder — inlined at session start."""
    sb = get_supabase()
    client = _load_client(sb, root_folder_id, user_id)
    return {"rules": client.list_eternal(limit=100)}


@router.get("/memories/recent")
async def list_recent(
    root_folder_id: str,
    days: int = 14,
    limit: int = 30,
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase()
    client = _load_client(sb, root_folder_id, user_id)
    return {"memories": client.list_recent_episodic(days=days, limit=limit)}


# ─── unified search (fan-out) ─────────────────────────────────────────
class UnifiedSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    root_folder_id: str | None = None
    limit: int = 10
    include_mem0: bool = True


@router.post("/unified-search")
async def unified_search(
    body: UnifiedSearchRequest, user_id: str = Depends(get_current_user)
):
    """Fan-out RAG docs + Mem0 in one call. This is what the MCP layer uses.
    Also demoable via curl for the audit endpoint validation.
    """
    sb = get_supabase()
    embedding = embed_query(body.query)
    result = await fanout_search(
        sb,
        embedding=embedding,
        query_text=body.query,
        user_id=user_id,
        folder_id=body.root_folder_id,
        limit=body.limit,
        include_mem0=body.include_mem0,
        channel="rest",
    )
    return {
        "query": result.query,
        "hits": [
            {
                "source": h.source,
                "id": h.id,
                "content": h.content,
                "metadata": h.metadata,
                "score": h.score,
            }
            for h in result.hits
        ],
        "sources_hit": result.sources_hit,
        "total_latency_ms": result.total_latency_ms,
    }
