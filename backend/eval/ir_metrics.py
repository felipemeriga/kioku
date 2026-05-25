"""Deterministic retrieval metrics: Recall@k, MRR, nDCG@k.

These are the load-bearing assertions in the eval harness CI gate. They do not
involve any LLM — same retrieved IDs against same labels → same numbers, every
time.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def recall_at_k(retrieved: list[str], relevant: set[str] | Iterable[str], k: int) -> float | None:
    """Fraction of relevant items found in the top-k retrieved.

    Returns None when `relevant` is empty (recall is undefined).
    """
    relevant_set = set(relevant)
    if not relevant_set:
        return None
    top_k = set(retrieved[:k])
    hits = top_k & relevant_set
    return len(hits) / len(relevant_set)


def mrr(retrieved: list[str], relevant: set[str] | Iterable[str]) -> float:
    """Reciprocal rank of the first relevant hit. 0 if none found."""
    relevant_set = set(relevant)
    for idx, doc_id in enumerate(retrieved, start=1):
        if doc_id in relevant_set:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str] | Iterable[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k. Binary relevance (0/1).

    DCG = sum_{i=1..k} rel_i / log2(i + 1)
    nDCG = DCG / IDCG where IDCG is DCG of the ideal ranking.
    """
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0

    def _gain(doc_id: str) -> int:
        return 1 if doc_id in relevant_set else 0

    dcg = sum(_gain(d) / math.log2(i + 2) for i, d in enumerate(retrieved[:k]))
    ideal_hits = min(len(relevant_set), k)
    idcg = sum(1 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0
