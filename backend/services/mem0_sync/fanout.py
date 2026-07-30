"""Memory fan-out — combines RAG document search and Mem0 memory search.

At retrieval time we hit two backends in parallel:
  1. Local RAG (services.search) over the folder's documents.
  2. Mem0 (if configured for this folder) over episodic + eternal memories.

Results are normalized to a common shape and merged. Every fan-out records
one row in retrieval_log so the memory quality is measurable over time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from services.search import search_documents

from .client import Mem0AppClient, MemoryScope, get_client_for_folder

log = logging.getLogger(__name__)


@dataclass
class UnifiedHit:
    source: str  # 'docs' | 'mem0_eternal' | 'mem0_episodic'
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    score: float | None = None


@dataclass
class FanoutResult:
    query: str
    hits: list[UnifiedHit]
    sources_hit: list[dict]  # [{source, count, latency_ms}]
    total_latency_ms: int


def _hits_from_docs(rag_rows: list[dict]) -> list[UnifiedHit]:
    out: list[UnifiedHit] = []
    for r in rag_rows or []:
        out.append(
            UnifiedHit(
                source="docs",
                id=f"docs:{r.get('id')}",
                content=(r.get("content") or "")[:2000],
                metadata=r.get("metadata") or {},
                score=r.get("similarity") or r.get("score"),
            )
        )
    return out


def _hits_from_mem0(rows: list[dict], scope: str) -> list[UnifiedHit]:
    label = "mem0_eternal" if scope == MemoryScope.ETERNAL else "mem0_episodic"
    out: list[UnifiedHit] = []
    for r in rows or []:
        md = r.get("metadata") or {}
        out.append(
            UnifiedHit(
                source=label,
                id=f"mem0:{r.get('id')}",
                content=r.get("memory") or "",
                metadata={
                    "category": md.get("category"),
                    "scope": md.get("scope"),
                    "tags": md.get("tags", []),
                    "written_by": md.get("written_by"),
                    "created_at": r.get("created_at"),
                },
                score=r.get("score"),
            )
        )
    return out


def _log_retrieval(
    sb,
    *,
    user_id: str,
    folder_id: str | None,
    query: str,
    hits: list[UnifiedHit],
    sources_hit: list[dict],
    latency_ms: int,
    channel: str,
    conversation_id: str | None = None,
) -> None:
    """Insert one retrieval_log row. Never blocks the retrieval path — swallow."""
    try:
        sb.table("retrieval_log").insert({
            "user_id": user_id,
            "folder_id": folder_id,
            "query": query,
            "sources_hit": sources_hit,
            "chunks_returned": len(hits),
            "chunk_ids": [h.id for h in hits[:50]],
            "latency_ms": latency_ms,
            "channel": channel,
        }).execute()
    except Exception:
        log.exception("failed to write retrieval_log row (non-fatal)")


def _resolve_root_folder_id(sb, folder_id: str | None, user_id: str) -> str | None:
    """Walk parent_id up to the workspace root.

    search_documents scopes by documents.root_folder_id (an exact match on the
    workspace root). The session's scope, however, is often a SUB-folder (e.g. a
    repo like cosm/repositories/c360-lead). Passing that sub-folder id straight
    through matched zero documents — their root_folder_id is the workspace root,
    not the sub-folder — so any repo/sub-folder session got 0 doc hits. Resolve
    to the actual root so the whole workspace tree is searchable from anywhere
    inside it. Returns folder_id unchanged on any lookup failure.
    """
    if not folder_id:
        return None
    current = folder_id
    seen: set[str] = set()
    for _ in range(32):  # depth guard against cycles / pathological trees
        if current in seen:
            break
        seen.add(current)
        try:
            res = (
                sb.table("folders")
                .select("parent_id")
                .eq("id", current)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception:
            return folder_id
        if not res.data:
            return folder_id
        parent = res.data[0].get("parent_id")
        if not parent:
            return current  # no parent → this is the root
        current = parent
    return current


async def _search_docs(
    sb,
    embedding: list[float],
    query_text: str,
    user_id: str,
    folder_id: str | None,
    limit: int,
) -> tuple[list[UnifiedHit], int]:
    t0 = time.perf_counter()

    def _run() -> list[dict]:
        # Resolve the workspace root in-thread (one quick lookup) so a session
        # scoped to a sub-folder still searches the whole tree.
        root_id = _resolve_root_folder_id(sb, folder_id, user_id)
        return search_documents(
            embedding,
            query_text=query_text,
            user_id=user_id,
            root_folder_id=root_id,
            fast_mode=True,
            top_k=limit,
        )

    try:
        rows = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("rag search failed: %s", e)
        rows = []
    latency = int((time.perf_counter() - t0) * 1000)
    return _hits_from_docs(rows), latency


async def _search_mem0(
    mem0: Mem0AppClient | None,
    query: str,
    limit: int,
) -> tuple[list[UnifiedHit], list[UnifiedHit], int]:
    """Returns (eternal_hits, episodic_hits, latency_ms). eternal is
    'get_all' (always inline), episodic is semantic 'search'."""
    if mem0 is None:
        return [], [], 0
    t0 = time.perf_counter()
    try:
        eternal, episodic = await asyncio.gather(
            asyncio.to_thread(mem0.list_eternal, 50),
            asyncio.to_thread(mem0.search, query, scope=MemoryScope.EPISODIC, limit=limit),
        )
    except Exception as e:
        log.exception("mem0 fan-out failed: %s", e)
        eternal, episodic = [], []
    latency = int((time.perf_counter() - t0) * 1000)
    return _hits_from_mem0(eternal, MemoryScope.ETERNAL), _hits_from_mem0(episodic, MemoryScope.EPISODIC), latency


def _merge_hits(
    doc_hits: list[UnifiedHit],
    mem0_eternal: list[UnifiedHit],
    mem0_episodic: list[UnifiedHit],
) -> list[UnifiedHit]:
    """Compose the final ranking.

    Order: eternal (always first — they're policy), then interleaved rag+episodic
    by score. Dedup by content hash so a memory that also lives as a doc chunk
    doesn't show twice.
    """
    seen: set[str] = set()
    result: list[UnifiedHit] = []

    for h in mem0_eternal:
        key = (h.content or "")[:200]
        if key in seen:
            continue
        seen.add(key)
        result.append(h)

    # Score-sort docs + episodic together, best first.
    scored = sorted(
        doc_hits + mem0_episodic,
        key=lambda h: (h.score if h.score is not None else 0.0),
        reverse=True,
    )
    for h in scored:
        key = (h.content or "")[:200]
        if key in seen:
            continue
        seen.add(key)
        result.append(h)
    return result


async def fanout_search(
    sb,
    *,
    embedding: list[float],
    query_text: str,
    user_id: str,
    folder_id: str | None,
    limit: int = 10,
    channel: str = "mcp",
    conversation_id: str | None = None,
    include_mem0: bool = True,
) -> FanoutResult:
    """Public entry point. Kicks RAG + Mem0 in parallel, merges, and logs."""
    t0 = time.perf_counter()
    mem0 = get_client_for_folder(sb, folder_id, user_id) if (include_mem0 and folder_id) else None

    doc_task = _search_docs(sb, embedding, query_text, user_id, folder_id, limit)
    mem0_task = _search_mem0(mem0, query_text, limit)

    (doc_hits, doc_ms), (m_eternal, m_episodic, mem0_ms) = await asyncio.gather(doc_task, mem0_task)

    merged = _merge_hits(doc_hits, m_eternal, m_episodic)[:limit + len(m_eternal)]
    total_ms = int((time.perf_counter() - t0) * 1000)

    sources_hit: list[dict] = [
        {"source": "docs", "count": len(doc_hits), "latency_ms": doc_ms}
    ]
    if mem0 is not None:
        sources_hit.append({
            "source": "mem0",
            "count": len(m_eternal) + len(m_episodic),
            "eternal": len(m_eternal),
            "episodic": len(m_episodic),
            "latency_ms": mem0_ms,
        })

    _log_retrieval(
        sb,
        user_id=user_id, folder_id=folder_id, query=query_text,
        hits=merged, sources_hit=sources_hit,
        latency_ms=total_ms, channel=channel, conversation_id=conversation_id,
    )

    return FanoutResult(
        query=query_text,
        hits=merged,
        sources_hit=sources_hit,
        total_latency_ms=total_ms,
    )
