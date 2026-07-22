"""Mem0 integration routes — memory proxy over the self-hosted mem0 service.

Memory is auto-on for repo folders (no "paste your API key" config). Every
request scopes to the current user; the client pins to (user_id, folder_id).
The hosted-platform config routes (connect/configs/verify) are gone.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase
from routes._validation import require_uuid
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


def _load_client(sb, folder_id: str, user_id: str) -> Mem0AppClient:
    """Return the memory client for a repo folder, or 404 if it isn't one."""
    require_uuid(folder_id, "Memory is only available on repo folders")
    client = get_client_for_folder(sb, folder_id, user_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Memory is only available on repo folders")
    return client


# ─── memory proxy ────────────────────────────────────────────────────────
class AddMemoryRequest(BaseModel):
    root_folder_id: str
    content: str = Field(min_length=1)
    category: str
    scope: str = "episodic"
    tags: list[str] | None = None
    written_by: str = "claude-code"


@router.post("/memories")
async def add_memory(body: AddMemoryRequest, user_id: str = Depends(get_current_user)):
    if body.category not in MemoryCategory.all():
        raise HTTPException(
            status_code=422,
            detail=f"category must be one of {list(MemoryCategory.all())}",
        )
    if body.scope not in ("eternal", "episodic"):
        raise HTTPException(status_code=422, detail="scope must be 'eternal' or 'episodic'")

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
    scope: str = "any"  # any | eternal | episodic
    limit: int = 10


@router.post("/search")
async def search_memory(body: SearchMemoryRequest, user_id: str = Depends(get_current_user)):
    sb = get_supabase()
    client = _load_client(sb, body.root_folder_id, user_id)
    scope = (
        body.scope if body.scope in (MemoryScope.ETERNAL, MemoryScope.EPISODIC) else MemoryScope.ANY
    )
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


@router.delete("/memories/{memory_id}")
async def delete_rule(
    memory_id: str,
    root_folder_id: str,
    user_id: str = Depends(get_current_user),
):
    """Delete a single memory in a repo folder (folder-scoped, not config-scoped)."""
    sb = get_supabase()
    client = _load_client(sb, root_folder_id, user_id)
    result = client.delete(memory_id)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "Mem0 delete failed")
    return {"ok": True}


@router.get("/status")
async def status(root_folder_id: str, user_id: str = Depends(get_current_user)):
    """Whether memory is available for this folder and the service is healthy."""
    sb = get_supabase()
    client = get_client_for_folder(sb, root_folder_id, user_id)
    if client is None:
        return {"available": False, "reason": "not a repo folder"}
    ok, err = client.ping()
    return {"available": True, "healthy": ok, "error": err}


# ─── unified search (fan-out) ─────────────────────────────────────────
class UnifiedSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    root_folder_id: str | None = None
    limit: int = 10
    include_mem0: bool = True


@router.post("/unified-search")
async def unified_search(body: UnifiedSearchRequest, user_id: str = Depends(get_current_user)):
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
