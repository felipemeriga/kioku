"""Rerank search results using Voyage AI reranker."""

import logging

import voyageai

from services.chunker import build_contextual_header
from services.metrics import record

logger = logging.getLogger(__name__)

_client: voyageai.Client | None = None


def _get_client() -> voyageai.Client:
    global _client
    if _client is None:
        _client = voyageai.Client()
    return _client


RERANK_SCORE_THRESHOLD = 0.2


def _scoring_text(doc: dict) -> str:
    """Reconstruct the contextualized chunk text that was indexed at embed time.

    The cross-encoder must score the same text shape that was indexed; otherwise
    it scores naked chunks stripped of filename/topic/keyword/position context
    and the contextual signal is lost.
    """
    metadata = doc.get("metadata") or {}
    header = build_contextual_header(metadata)
    return f"{header}\n\n{doc['content']}"


def rerank(
    query: str,
    documents: list[dict],
    top_k: int = 5,
    score_threshold: float = RERANK_SCORE_THRESHOLD,
) -> list[dict]:
    """Rerank documents by relevance to query using voyage-rerank-2.

    Each document dict must have a 'content' key.
    Returns the top_k most relevant documents with rerank_score added.
    Documents below score_threshold are filtered out to avoid feeding
    irrelevant chunks to the LLM.
    Falls back to returning the first top_k documents if reranking fails.
    """
    if not documents:
        record("rerank", n_in=0, n_kept=0, n_dropped=0)
        return []

    try:
        texts = [_scoring_text(doc) for doc in documents]
        result = _get_client().rerank(
            query=query,
            documents=texts,
            model="rerank-2",
            top_k=min(top_k, len(documents)),
        )

        all_scores = [r.relevance_score for r in result.results]
        reranked = []
        for r in result.results:
            if r.relevance_score < score_threshold:
                continue
            doc = documents[r.index].copy()
            doc["rerank_score"] = r.relevance_score
            reranked.append(doc)

        record(
            "rerank",
            n_in=len(documents),
            n_kept=len(reranked),
            n_dropped=len(documents) - len(reranked),
            score_p50=_percentile(all_scores, 50),
            score_p95=_percentile(all_scores, 95),
        )
        return reranked
    except Exception:
        logger.warning("Voyage reranker failed, falling back to un-reranked results")
        record(
            "rerank",
            n_in=len(documents),
            n_kept=min(top_k, len(documents)),
            n_dropped=0,
            score_p50=None,
            score_p95=None,
            failed=True,
        )
        return documents[:top_k]


def _percentile(values: list[float], p: int) -> float | None:
    """Quick-and-dirty percentile. Returns None on empty input."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (p / 100)
    f = int(k)
    if f == len(s) - 1:
        return round(s[f], 3)
    return round(s[f] + (s[f + 1] - s[f]) * (k - f), 3)
