"""Temporal retrieval integration check — the REAL pipeline, no mocks.

Seeds synthetic dated chunks (real Voyage embeddings) into the connected
Supabase, runs `search_documents` end-to-end (hybrid search → RRF → real
reranker → recency decay), asserts the temporal bottleneck scenarios, and
deletes the seeded rows in a finally block.

Scenarios (the bottlenecks this guards):
  S1  Equal relevance, different age  → fresh meeting outranks stale twin.
  S2  Anchor pollution ("SMT case")   → a highly-relevant year-old meeting
      beats a fresh chunk that merely mentions the term.
  S3  All-old cohort                  → when every relevant chunk is old
      (folder untouched for a year), pure relevance order is preserved.
  S4  Reference material              → old PDFs never decay; relevance wins.
  S5  created_after filter            → date bounds actually exclude rows.
  S6  Dates travel with results       → created_at present on every hit.

Run inside the backend environment (needs SUPABASE + VOYAGE credentials):
    python -m eval.temporal_eval <user_id>
Exits 0 when all scenarios pass, 1 otherwise.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone

from db.client import get_supabase
from services.embeddings import embed_batch, embed_query
from services.search import search_documents

PREFIX = "temporal-eval-"

# (name, age_days, source_type, content)
SEED = [
    (
        "smt-old-decision",
        365,
        "meeting",
        "Meeting notes: after benchmarking, we decided the SMT ingestion latency "
        "budget is 250ms end-to-end, with the parser capped at 80ms and the network "
        "hop at 120ms. This is the agreed SMT latency decision going forward.",
    ),
    (
        "smt-fresh-mention",
        1,
        "meeting",
        "Weekly sync notes: mostly discussed the new marketing website. Someone "
        "briefly asked whether SMT was affected; it was not. Main topics were "
        "hiring, website copy, and the offsite agenda.",
    ),
    (
        "old-strong-reco",
        370,
        "meeting",
        "Architecture review: the recommendation engine uses collaborative "
        "filtering with matrix factorization, retrained nightly at 02:00 UTC "
        "from the events warehouse.",
    ),
    (
        "old-weak-reco",
        350,
        "meeting",
        "Standup notes: quick status across services; the recommendation engine "
        "was briefly noted as unchanged this sprint.",
    ),
    (
        "twin-old",
        200,
        "meeting",
        "Deploy runbook discussion: blue-green deploys for the payments service "
        "require draining webhook consumers before switching traffic.",
    ),
    (
        "twin-fresh",
        2,
        "meeting",
        "Deploy runbook discussion: blue-green deploys for the payments service "
        "require draining webhook consumers before switching traffic.",
    ),
    (
        "ref-old-strong",
        400,
        "pdf",
        "API reference: the /v2/orders endpoint accepts idempotency keys via the "
        "Idempotency-Key header; client retries must reuse the same key.",
    ),
    (
        "ref-fresh-weak",
        3,
        "pdf",
        "Changelog: minor documentation cleanup across API pages, no behavior "
        "changes to orders or any other endpoint.",
    ),
]


def _seed(sb, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    embeddings = embed_batch([content for _, _, _, content in SEED])
    rows = []
    for (name, age_days, source_type, content), embedding in zip(SEED, embeddings, strict=True):
        rows.append(
            {
                "user_id": user_id,
                "source_filename": f"{PREFIX}{name}",
                "source_type": source_type,
                "content": content,
                "embedding": embedding,
                "status": "completed",
                "content_hash": uuid.uuid4().hex,
                "created_at": (now - timedelta(days=age_days)).isoformat(),
                "metadata": {"source_filename": f"{PREFIX}{name}", "chunk_index": 0},
            }
        )
    sb.table("documents").insert(rows).execute()


def _cleanup(sb, user_id: str) -> None:
    (
        sb.table("documents")
        .delete()
        .eq("user_id", user_id)
        .like("source_filename", f"{PREFIX}%")
        .execute()
    )


def _search(user_id: str, query: str, **kwargs) -> list[dict]:
    results = search_documents(
        embed_query(query),
        query_text=query,
        user_id=user_id,
        fast_mode=True,
        top_k=5,
        **kwargs,
    )
    # Only look at our synthetic rows so the user's real corpus (which can
    # legitimately match) never affects the assertions.
    return [
        r
        for r in results
        if ((r.get("metadata") or {}).get("source_filename", "")).startswith(PREFIX)
    ]


def _names(results: list[dict]) -> list[str]:
    return [(r.get("metadata") or {})["source_filename"].removeprefix(PREFIX) for r in results]


def _report(label: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
    return ok


def run(user_id: str) -> int:
    sb = get_supabase()
    failures = 0
    try:
        print(f"seeding {len(SEED)} dated chunks (prefix {PREFIX!r})...")
        _seed(sb, user_id)

        # S1 — equal relevance, tie broken by freshness
        r = _search(user_id, "how do blue-green deploys for the payments service work?")
        names = _names(r)
        ok = (
            "twin-fresh" in names
            and "twin-old" in names
            and names.index("twin-fresh") < names.index("twin-old")
        )
        failures += not _report("S1 fresh-wins-tie", ok, f"order={names}")

        # S2 — anchor pollution: relevant old beats marginal fresh
        r = _search(user_id, "what is the SMT ingestion latency budget decision?")
        names = _names(r)
        ok = bool(names) and names[0] == "smt-old-decision"
        failures += not _report("S2 old-relevant-beats-fresh-mention", ok, f"order={names}")

        # S3 — all-old cohort keeps relevance order
        r = _search(user_id, "how does the recommendation engine work?")
        names = _names(r)
        ok = bool(names) and names[0] == "old-strong-reco"
        failures += not _report("S3 all-old-cohort-relevance-order", ok, f"order={names}")

        # S4 — reference material never decays
        r = _search(user_id, "how do I pass idempotency keys to the orders API?")
        names = _names(r)
        ok = bool(names) and names[0] == "ref-old-strong"
        failures += not _report("S4 reference-docs-no-decay", ok, f"order={names}")

        # S5 — created_after excludes old rows
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        r = _search(
            user_id,
            "what is the SMT ingestion latency budget decision?",
            created_after=cutoff,
        )
        names = _names(r)
        ok = "smt-old-decision" not in names
        failures += not _report("S5 created-after-filters", ok, f"order={names}")

        # S6 — dates travel with results
        r = _search(user_id, "how do blue-green deploys for the payments service work?")
        ok = bool(r) and all(x.get("created_at") for x in r)
        failures += not _report("S6 dates-on-results", ok, f"n={len(r)}")
    finally:
        _cleanup(sb, user_id)
        print("cleanup: seeded rows deleted")

    print(f"\n{'ALL SCENARIOS PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m eval.temporal_eval <user_id>")
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
