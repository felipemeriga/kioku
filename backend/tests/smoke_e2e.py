"""End-to-end smoke test for the retrieval pipeline.

Hits real Supabase, Voyage embed, Voyage rerank. Not part of unittest
discovery (filename doesn't start with test_). Run with:

    cd backend && uv run python -m tests.smoke_e2e

Useful for validating the parallelization savings introduced in PR #16.
"""

import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from db.client import get_supabase  # noqa: E402
from services.embeddings import embed_query  # noqa: E402
from services.search import search_documents  # noqa: E402


def _pick_user_id() -> str:
    """Pick the user_id with the most documents — the real user."""
    sb = get_supabase()
    rows = sb.table("documents").select("user_id").limit(1000).execute()
    counts: dict[str, int] = {}
    for row in rows.data:
        uid = row.get("user_id")
        if uid:
            counts[uid] = counts.get(uid, 0) + 1
    if not counts:
        raise RuntimeError("No documents found in the DB. Ingest something first.")
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _time(label: str, fn, *args, **kwargs):
    t0 = time.monotonic()
    result = fn(*args, **kwargs)
    elapsed = time.monotonic() - t0
    print(f"  [{elapsed * 1000:7.1f} ms] {label}")
    return result, elapsed


def main() -> int:
    user_id = _pick_user_id()
    print(f"user_id = {user_id}\n")

    query = "what data does Hawk-Eye provide for basketball games?"
    print(f"query   = {query!r}\n")

    print("--- query embed (warmup, also used by both modes below) ---")
    embedding, _ = _time("embed_query", embed_query, query)

    print("\n--- FAST mode (should be 1-3s) ---")
    fast_results, fast_total = _time(
        "search_documents fast_mode=True",
        search_documents,
        query_embedding=embedding,
        query_text=query,
        user_id=user_id,
        top_k=5,
        fast_mode=True,
    )

    print("\n--- FULL mode (should be 5-10s with parallelization; was 15-20s before) ---")
    full_results, full_total = _time(
        "search_documents fast_mode=False",
        search_documents,
        query_embedding=embedding,
        query_text=query,
        user_id=user_id,
        top_k=5,
        fast_mode=False,
    )

    print("\n--- summary ---")
    print(f"  fast mode hits: {len(fast_results)} docs, {fast_total * 1000:.0f} ms")
    print(f"  full mode hits: {len(full_results)} docs, {full_total * 1000:.0f} ms")
    print(f"  overhead of full mode: +{(full_total - fast_total) * 1000:.0f} ms")

    if fast_results:
        print("\n--- fast mode top-1 ---")
        top = fast_results[0]
        source = top.get("source_filename") or (top.get("metadata") or {}).get("source_filename")
        print(f"  source   : {source}")
        score = top.get("rerank_score")
        print(f"  rerank   : {score:.3f}" if score is not None else "  rerank   : -")
        print(f"  expanded : {top.get('expanded', False)}")
        snippet = top.get("content", "")[:200].replace("\n", " ")
        print(f"  content  : {snippet}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
