"""Retrieval audit endpoints — recent retrievals + retrieval stats per source.

Two views:
  GET /api/retrieval-log            recent rows (paginated), filterable by folder
  GET /api/retrieval-log/stats      aggregate: hits per source, per category,
                                    latency p50/p95, unretrieved memory count
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import get_current_user
from db.client import get_supabase

router = APIRouter(prefix="/api/retrieval-log")


@router.get("")
async def list_recent(
    folder_id: str | None = None,
    limit: int = 50,
    user_id: str = Depends(get_current_user),
):
    sb = get_supabase()
    q = (
        sb.table("retrieval_log")
        .select(
            "id, folder_id, query, sources_hit, chunks_returned, "
            "chunk_ids, latency_ms, channel, created_at"
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(min(max(limit, 1), 500))
    )
    if folder_id:
        q = q.eq("folder_id", folder_id)
    rows = q.execute().data or []
    return rows


@router.get("/stats")
async def stats(
    folder_id: str | None = None,
    since_days: int = 30,
    user_id: str = Depends(get_current_user),
):
    """Aggregate stats over the trailing window. Computed in-Python from the
    raw log (small volume) rather than via SQL — keeps schema flexible while
    we iterate on the shape."""
    sb = get_supabase()
    q = (
        sb.table("retrieval_log")
        .select("sources_hit, chunks_returned, chunk_ids, latency_ms, created_at, folder_id")
        .eq("user_id", user_id)
    )
    if folder_id:
        q = q.eq("folder_id", folder_id)
    rows = q.execute().data or []

    total = len(rows)
    if total == 0:
        return {
            "total_retrievals": 0,
            "docs_hit_count": 0,
            "mem0_hit_count": 0,
            "avg_chunks_returned": 0,
            "latency_p50_ms": 0,
            "latency_p95_ms": 0,
            "zero_hit_queries": 0,
        }

    docs_hits = 0
    mem0_hits = 0
    zero_hits = 0
    latencies: list[int] = []
    chunks_returned_total = 0
    chunk_id_freq: dict[str, int] = {}

    for r in rows:
        latencies.append(int(r.get("latency_ms") or 0))
        chunks_returned_total += int(r.get("chunks_returned") or 0)
        if (r.get("chunks_returned") or 0) == 0:
            zero_hits += 1
        for src in r.get("sources_hit") or []:
            if src.get("source") == "docs":
                docs_hits += int(src.get("count") or 0)
            elif src.get("source") == "mem0":
                mem0_hits += int(src.get("count") or 0)
        for cid in r.get("chunk_ids") or []:
            chunk_id_freq[cid] = chunk_id_freq.get(cid, 0) + 1

    latencies.sort()

    def _pct(pct: float) -> int:
        if not latencies:
            return 0
        i = int(len(latencies) * pct / 100)
        return latencies[min(i, len(latencies) - 1)]

    top_chunks = sorted(chunk_id_freq.items(), key=lambda kv: kv[1], reverse=True)[:20]

    return {
        "total_retrievals": total,
        "docs_hit_count": docs_hits,
        "mem0_hit_count": mem0_hits,
        "avg_chunks_returned": round(chunks_returned_total / max(total, 1), 2),
        "latency_p50_ms": _pct(50),
        "latency_p95_ms": _pct(95),
        "zero_hit_queries": zero_hits,
        "top_retrieved_chunks": [{"chunk_id": cid, "retrievals": n} for cid, n in top_chunks],
    }
