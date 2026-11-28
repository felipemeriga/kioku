"""Check evidence for the three explicit q020 choices on seeded local fixtures.

Run from the backend directory after `python -m eval.runner --gate`:
    python -m eval.document_facets
"""

import os

import yaml

from eval.runner import EVAL_FOLDER_ID, EVAL_USER_ID, GOLDEN_SET, _guard_against_prod
from services.embeddings import embed_query
from services.metrics import collect_request
from services.search import search_documents

EXPECTED = {
    "ANN index": ("ivfflat_indexes.md", ("IVFFlat", "nprobe")),
    "Keyword search": ("postgres_tsvector.md", ("tsvector", "GIN")),
    "Result fusion": ("rrf_fusion.md", ("Reciprocal Rank Fusion",)),
}


def main() -> int:
    _guard_against_prod(allow_remote=False)
    question = next(
        q["question"] for q in yaml.safe_load(GOLDEN_SET.read_text()) if q["id"] == "q020"
    )
    os.environ["RAG_METRICS"] = "1"
    with collect_request("q020 local source-facet smoke") as metrics:
        hits = search_documents(
            embed_query(question),
            query_text=question,
            user_id=EVAL_USER_ID,
            folder_ids=[EVAL_FOLDER_ID],
            fast_mode=True,
            top_k=5,
        )
    passed = True
    for facet, (filename, phrases) in EXPECTED.items():
        rank = next(
            (
                rank
                for rank, hit in enumerate(hits, 1)
                if (hit.get("metadata") or {}).get("source_filename") == filename
                and all(phrase.casefold() in hit["content"].casefold() for phrase in phrases)
            ),
            None,
        )
        print(f"{'PASS' if rank else 'FAIL'} {facet}: {filename} at rank {rank}")
        passed = passed and rank is not None
    facet_rerank_ran = metrics is not None and any(
        name == "document_facets" and not data["degraded"] for name, data in metrics._stages
    )
    print(f"{'PASS' if facet_rerank_ran else 'FAIL'} Parallel facet rerank")
    return 0 if passed and facet_rerank_ran else 1


if __name__ == "__main__":
    raise SystemExit(main())
