"""Document and code retrieval shared by MCP and CLI, with audit logging."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from starlette.concurrency import run_in_threadpool

from db.client import get_supabase_thread_safe
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
    """Write audit metadata in a worker; failures are non-fatal."""
    try:
        client = sb if sb is not None else get_supabase_thread_safe()
        client.table("retrieval_log").insert(
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
    """Resolve the authorized root in one existing ownership-filtered SQL call."""
    if not folder_id:
        return None
    try:
        rows = (
            sb.rpc("folder_breadcrumbs", {"p_folder_id": folder_id, "p_user_id": user_id})
            .execute()
            .data
            or []
        )
    except Exception:
        return folder_id
    # Empty/failed lookups retain the original restriction; never widen to all folders.
    return rows[0]["id"] if rows else folder_id


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
        client = sb if sb is not None else get_supabase_thread_safe()
        root_id = _resolve_root_folder_id(client, folder_id, user_id)
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
        rows = await run_in_threadpool(_run)
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
    await run_in_threadpool(
        _log_retrieval,
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
        total_latency_ms=int((time.perf_counter() - t0) * 1000),
    )
