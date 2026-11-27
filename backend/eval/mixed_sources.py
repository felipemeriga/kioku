"""Small synthetic mixed-source ranking checks for the local eval database."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from db.client import get_supabase
from services.embeddings import embed_code_batch, embed_query
from services.ingestion import ingest_document
from services.metrics import collect_request
from services.search import search_documents

DEFINITION = (
    "# Lumen relay vendor guide\n\n"
    "Lumen relay burst delivery emits an update immediately for every event. "
    "Digest delivery combines updates into one snapshot every ten seconds. "
    "Use burst for alerts that require immediate action and digest for dashboards. "
    "These delivery modes control notification timing, not event persistence."
)
OVERRIDE = (
    "# Lumen relay lab override\n\n"
    "In the independent Lumen relay test lab, burst delivery waits three seconds. "
    "Digest delivery emits a combined snapshot every sixty seconds. "
    "This is the lab override for burst versus digest delivery."
)
DECODER = """def decode_delivery_mode(topic: str) -> str:
    if topic.endswith(".burst"):
        return "burst"
    if topic.endswith(".digest"):
        return "digest"
    raise ValueError("unknown Lumen relay topic suffix")
"""
CONSUMER_COPIES = """def render_lumen_relay_delivery(mode: str) -> str:
    if mode == "burst":
        return "event update"
    return "digest snapshot"
"""


def run_mixed_sources(user_id: str) -> list[dict]:
    """Seed disposable rows and verify specific evidence at a five-hit budget."""
    sb = get_supabase()
    scope = str(uuid4())
    foreign = str(uuid4())
    folders = [scope, foreign]
    sb.table("folders").insert(
        [
            {"id": scope, "user_id": user_id, "name": f"Eval Lumen {scope}", "kind": "repo"},
            {
                "id": foreign,
                "user_id": user_id,
                "name": f"Eval Lumen Lab {foreign}",
                "kind": "repo",
            },
        ]
    ).execute()
    try:

        def ingest(filename: str, text: str, folder: str) -> set[str]:
            return set(
                ingest_document(text.encode(), filename, user_id, folder_id=folder)["document_ids"]
            )

        definition = ingest("lumen-vendor-guide.md", DEFINITION, scope)
        override = ingest("lumen-lab-override.md", OVERRIDE, foreign)
        files = [
            (scope, "delivery.py", "decode_delivery_mode", DECODER),
            (scope, "dashboard.py", "render_lumen_relay_delivery", CONSUMER_COPIES),
            (scope, "dashboard_copy.py", "render_lumen_relay_delivery", CONSUMER_COPIES),
            (foreign, "lab_delivery.py", "decode_delivery_mode", DECODER),
        ]
        for name, mode in (("alert", "burst"), ("report", "digest"), ("snapshot", "digest")):
            files.append(
                (
                    scope,
                    f"{name}.py",
                    f"publish_{name}",
                    f'def publish_{name}(relay, event):\n    topic = "lumen.{mode}"\n'
                    f"    return relay.send(topic, event)\n",
                )
            )

        rows = []
        for folder, path, symbol, body in files:
            lines = len(body.splitlines())
            rows.append(
                {
                    "id": str(uuid4()),
                    "user_id": user_id,
                    "folder_id": folder,
                    "file": path,
                    "symbol": symbol,
                    "language": "python",
                    "start_line": 1,
                    "end_line": lines,
                    "content": f"[repo lumen] [file {path}:1-{lines}] [symbol {symbol}]\n{body}",
                    "file_hash": hashlib.sha256(body.encode()).hexdigest(),
                }
            )
        embeddings = embed_code_batch([row["content"] for row in rows])
        for row, embedding in zip(rows, embeddings, strict=True):
            row["embedding"] = embedding
        sb.table("code_chunks").insert(rows).execute()

        decoder, dashboard, copy, lab_decoder, *_ = (row["id"] for row in rows)
        scoped = definition | {row["id"] for row in rows if row["folder_id"] == scope}
        results = []
        cases = [
            (
                "definition",
                "What is the difference between Lumen relay burst and digest delivery?",
                scope,
                scoped,
                [(definition, 2)],
            ),
            (
                "implementation",
                "Where does decode_delivery_mode map Lumen relay topic suffixes?",
                scope,
                scoped,
                [({decoder}, 3)],
            ),
            (
                "mixed",
                "Compare the Lumen relay vendor guide with our decode_delivery_mode "
                "implementation for burst and digest delivery.",
                scope,
                scoped,
                [(definition, 5), ({decoder}, 5)],
            ),
            (
                "foreign_scope",
                "What is the Lumen relay test lab override for burst and digest delivery?",
                foreign,
                override | {lab_decoder},
                [(override, 2)],
            ),
        ]
        for name, query, folder, allowed, required in cases:
            with collect_request(f"eval mixed sources {name}") as metrics:
                hits = search_documents(
                    embed_query(query),
                    query_text=query,
                    user_id=user_id,
                    fast_mode=True,
                    top_k=5,
                    folder_ids=[folder],
                )
            ranked = [hit["id"] for hit in hits]
            rerank = next(
                (data for stage, data in (metrics._stages if metrics else []) if stage == "rerank"),
                {},
            )
            rerank_ok = rerank.get("n_kept", 0) > 0 and not rerank.get("failed")
            coverage = all(ids.intersection(ranked[:cutoff]) for ids, cutoff in required)
            isolated = set(ranked) <= allowed
            candidate_count = rerank.get("n_in")
            expected_candidates = len(allowed) - (folder == scope)
            deduplicated = candidate_count == expected_candidates and not {
                dashboard,
                copy,
            }.issubset(ranked)
            results.append(
                {
                    "id": name,
                    "passed": rerank_ok and coverage and isolated and deduplicated,
                    "evidence_found": coverage,
                    "scope_isolated": isolated,
                    "copies_deduplicated": deduplicated,
                    "reranker_used": rerank_ok,
                    "reranker_candidates": candidate_count,
                    "ranked_sources": [hit["metadata"]["source_filename"] for hit in hits],
                }
            )
        return results
    finally:
        sb.table("documents").delete().eq("user_id", user_id).in_("folder_id", folders).execute()
        sb.table("folders").delete().eq("user_id", user_id).in_("id", folders).execute()
