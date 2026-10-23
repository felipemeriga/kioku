"""Document and code retrieval shared by MCP and CLI, with audit logging."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from services.search import search_documents

log = logging.getLogger(__name__)


@dataclass
class UnifiedHit:
    source: str  # 'docs' (including indexed code)
    id: str
    content: str
    metadata: dict = field(default_factory=dict)
    score: float | None = None


@dataclass
class RetrievalResult:
    query: str
    hits: list[UnifiedHit]
    sources_hit: list[dict]  # [{source, count, latency_ms}]
    total_latency_ms: int


def _hits_from_docs(rag_rows: list[dict]) -> list[UnifiedHit]:
    out: list[UnifiedHit] = []
    for r in rag_rows or []:
        # Surface the source date so MCP consumers can weigh freshness.
        metadata = dict(r.get("metadata") or {})
        if r.get("created_at") and "created_at" not in metadata:
            metadata["created_at"] = str(r["created_at"])
        if r.get("last_updated"):
            metadata["last_updated"] = str(r["last_updated"])
        out.append(
            UnifiedHit(
                source="docs",
                id=f"docs:{r.get('id')}",
                content=(r.get("content") or "")[:2000],
                metadata=metadata,
                score=r.get("similarity") or r.get("score"),
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
        sb.table("retrieval_log").insert(
            {
                "user_id": user_id,
                "folder_id": folder_id,
                "query": query,
                "sources_hit": sources_hit,
                "chunks_returned": len(hits),
                "chunk_ids": [h.id for h in hits[:50]],
                "latency_ms": latency_ms,
                "channel": channel,
            }
        ).execute()
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
    folder_ids: list[str] | None = None,
    source_filename: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> tuple[list[UnifiedHit], int]:
    t0 = time.perf_counter()

    def _run() -> list[dict]:
        # Resolve the workspace root in-thread (one quick lookup) so a session
        # scoped to a sub-folder still searches the whole tree — unless the
        # caller narrowed retrieval to an explicit subtree or file.
        root_id = _resolve_root_folder_id(sb, folder_id, user_id)
        return search_documents(
            embedding,
            query_text=query_text,
            user_id=user_id,
            root_folder_id=root_id,
            fast_mode=True,
            top_k=limit,
            folder_ids=folder_ids,
            source_filename=source_filename,
            created_after=created_after,
            created_before=created_before,
        )

    try:
        rows = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("rag search failed: %s", e)
        rows = []
    latency = int((time.perf_counter() - t0) * 1000)
    return _hits_from_docs(rows), latency


async def retrieve_knowledge(
    sb,
    *,
    embedding: list[float],
    query_text: str,
    user_id: str,
    folder_id: str | None,
    limit: int = 10,
    channel: str = "mcp",
    conversation_id: str | None = None,
    folder_ids: list[str] | None = None,
    source_filename: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> RetrievalResult:
    """Retrieve documents and indexed code, preserving filters and audit logs."""
    t0 = time.perf_counter()
    hits, doc_ms = await _search_docs(
        sb,
        embedding,
        query_text,
        user_id,
        folder_id,
        limit,
        folder_ids,
        source_filename,
        created_after,
        created_before,
    )
    hits = hits[:limit]
    total_ms = int((time.perf_counter() - t0) * 1000)
    sources_hit = [{"source": "docs", "count": len(hits), "latency_ms": doc_ms}]
    _log_retrieval(
        sb,
        user_id=user_id,
        folder_id=folder_id,
        query=query_text,
        hits=hits,
        sources_hit=sources_hit,
        latency_ms=total_ms,
        channel=channel,
        conversation_id=conversation_id,
    )
    return RetrievalResult(
        query=query_text,
        hits=hits,
        sources_hit=sources_hit,
        total_latency_ms=total_ms,
    )
