"""Code-blend retrieval check — the REAL pipeline, no mocks.

Guards the knowledge_base_search code blending (doc chunks + code chunks
joint-reranked): seeds controlled DOC chunks (real Voyage embeddings) into
the connected Supabase, then runs `search_documents` end-to-end against the
seeded docs PLUS the user's real code_chunks corpus, asserting the three
regimes the blend must get right:

  A  doc-only questions   → code must NOT crowd out the answering doc
     (no code hit may rank above it; top-3 stays doc-dominated).
  B  concept + code       → BOTH modalities must appear: the design doc
     AND the implementing source file land in the same result list.
  C  code-only questions  → the right source file must rank in the top-3,
     found via the blend (no code_search tool involved).

The doc side is seeded (deterministic); the code side is the user's real
indexed corpus, so this exercises exactly what production retrieval sees.
Seeded rows are deleted in a finally block.

Run inside the backend environment (needs SUPABASE + VOYAGE credentials
and a user with the kioku repo code-indexed):
    python -m eval.blend_eval <user_id>
Exits 0 when all cases pass, 1 otherwise.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone

from db.client import get_supabase
from services.embeddings import embed_batch, embed_query
from services.search import search_documents

PREFIX = "blend-eval-"

# (name, content) — reference material, embeds with the real doc model.
SEED = [
    (
        "vacation-policy",
        "HR policy: full-time employees receive 30 vacation days per year, "
        "accrued monthly. Unused days roll over up to a maximum of 10 days. "
        "Vacation requests need manager approval two weeks in advance.",
    ),
    (
        "pricing-draft",
        "Pricing plan draft: kioku Pro costs $12 per month and includes up to "
        "5 linked repositories, unlimited documents, and Notion sync. The free "
        "tier is limited to 1 repository and 100 documents.",
    ),
    (
        "recency-design-note",
        "Design note — recency in kioku retrieval: ranking uses a bounded "
        "additive blend, final score = 0.8 * relevance + 0.2 * recency, with "
        "cohort-relative normalization so an all-old result set keeps pure "
        "relevance order. Half-lives: meetings decay at 90 days, audio at 180 "
        "days; reference documents and code never decay.",
    ),
    (
        "watcher-runbook",
        "Runbook — kioku repo watcher: a scheduled service runs twice a day at "
        "06:00 and 18:00 UTC. Each pass decrypts the owner's ed25519 git key, "
        "checks the principal branch head with ls-remote, and skips any repo "
        "whose SHA is unchanged. Auth failures are recorded in last_error, "
        "never silent.",
    ),
]

# (label, query, expectations) — see _check_* for the assertion semantics.
DOC_ONLY = [
    ("A1 vacation", "how many vacation days do employees get per year?", "vacation-policy"),
    ("A2 pricing", "what does kioku Pro cost per month?", "pricing-draft"),
]
CONCEPT_AND_CODE = [
    (
        "B1 recency",
        "how does recency decay ranking work in retrieval?",
        "recency-design-note",
        "services/search.py",
    ),
    (
        "B2 watcher",
        "when does the repo watcher run and how does it skip unchanged repos?",
        "watcher-runbook",
        "watcher.py",
    ),
]
CODE_ONLY = [
    (
        "C1 fernet",
        "python function that decrypts the stored git ssh private key with fernet",
        "watcher/watcher.py",
    ),
    (
        "C2 file-hash",
        "where do we compute sha256 content hashes of files before uploading code chunks",
        "code-chunks.ts",
    ),
    (
        "C3 arq-redis",
        "arq worker redis connection retry and timeout settings",
        "queue/settings.py",
    ),
]


def _seed(sb, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    embeddings = embed_batch([content for _, content in SEED])
    rows = []
    for (name, content), embedding in zip(SEED, embeddings, strict=True):
        rows.append(
            {
                "user_id": user_id,
                "source_filename": f"{PREFIX}{name}",
                "source_type": "text",
                "content": content,
                "embedding": embedding,
                "status": "completed",
                "content_hash": uuid.uuid4().hex,
                "created_at": now.isoformat(),
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


def _search(user_id: str, query: str) -> list[dict]:
    return search_documents(
        embed_query(query),
        query_text=query,
        user_id=user_id,
        fast_mode=True,
        top_k=8,
    )


def _describe(r: dict) -> str:
    meta = r.get("metadata") or {}
    src = meta.get("source_filename", "?")
    kind = "code" if r.get("source_type") == "code" else "doc"
    return f"{kind}:{src}"


def _is_code(r: dict) -> bool:
    return r.get("source_type") == "code"


def _doc_rank(results: list[dict], seeded_name: str) -> int | None:
    """Rank (0-based) of a seeded doc in the results, or None."""
    for i, r in enumerate(results):
        src = (r.get("metadata") or {}).get("source_filename", "")
        if src == f"{PREFIX}{seeded_name}":
            return i
    return None


def _code_rank(results: list[dict], file_fragment: str) -> int | None:
    """Rank (0-based) of the first code hit whose file matches, or None."""
    for i, r in enumerate(results):
        if not _is_code(r):
            continue
        src = (r.get("metadata") or {}).get("source_filename", "")
        if file_fragment in src:
            return i
    return None


def _report(label: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")
    return ok


def run(user_id: str) -> int:
    sb = get_supabase()
    failures = 0
    try:
        print(f"seeding {len(SEED)} doc chunks (prefix {PREFIX!r})...")
        _seed(sb, user_id)

        # A — doc-only: the answering doc must beat every code hit, and the
        # top-3 must not be swamped by code.
        for label, query, seeded in DOC_ONLY:
            r = _search(user_id, query)
            ranked = [_describe(x) for x in r]
            doc_at = _doc_rank(r, seeded)
            first_code = next((i for i, x in enumerate(r) if _is_code(x)), None)
            code_in_top3 = sum(1 for x in r[:3] if _is_code(x))
            ok = (
                doc_at is not None
                and (first_code is None or doc_at < first_code)
                and code_in_top3 == 0
            )
            failures += not _report(
                label,
                ok,
                f"doc@{doc_at} first_code@{first_code} code_in_top3={code_in_top3} | {ranked[:5]}",
            )

        # B — concept + code: both the seeded design doc and the implementing
        # source file must appear in the same blended result list.
        for label, query, seeded, code_file in CONCEPT_AND_CODE:
            r = _search(user_id, query)
            ranked = [_describe(x) for x in r]
            doc_at = _doc_rank(r, seeded)
            code_at = _code_rank(r, code_file)
            ok = doc_at is not None and code_at is not None
            failures += not _report(
                label, ok, f"doc@{doc_at} code[{code_file}]@{code_at} | {ranked[:6]}"
            )

        # C — code-only: the right source file must rank in the top-3 of the
        # blended list (docs may appear, but must not bury the code).
        for label, query, code_file in CODE_ONLY:
            r = _search(user_id, query)
            ranked = [_describe(x) for x in r]
            code_at = _code_rank(r, code_file)
            ok = code_at is not None and code_at < 3
            failures += not _report(label, ok, f"code[{code_file}]@{code_at} | {ranked[:5]}")

        # Shape invariants: every code hit is locatable (file:start-end) and
        # dated. code_symbol is optional — file-preamble chunks have none.
        r = _search(user_id, "how does the repo watcher decrypt git keys?")
        code_hits = [x for x in r if _is_code(x)]
        ok = bool(code_hits) and all(
            ":" in (x.get("metadata") or {}).get("source_filename", "") and x.get("created_at")
            for x in code_hits
        )
        failures += not _report("D1 code-hit-shape", ok, f"n_code={len(code_hits)}")
    finally:
        _cleanup(sb, user_id)
        print("cleanup: seeded rows deleted")

    print(f"\n{'ALL CASES PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m eval.blend_eval <user_id>")
        sys.exit(2)
    sys.exit(run(sys.argv[1]))
