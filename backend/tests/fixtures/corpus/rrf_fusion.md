# Reciprocal Rank Fusion (RRF)

Reciprocal Rank Fusion is a simple, parameter-light algorithm for combining
multiple ranked result lists into a single fused ranking. It is widely used
in hybrid search systems to merge results from vector search and keyword search.

## The Formula

For each document `d` appearing in one or more ranked lists, the RRF score is:

```
RRF(d) = sum over each list L of: 1 / (k + rank(d, L))
```

Where:
- `rank(d, L)` is the position of document `d` in list `L` (1-indexed).
- `k` is a constant (commonly 60) that smooths the impact of high-ranked items.
- If document `d` does not appear in list `L`, it contributes 0 for that list.

The final ranking sorts documents by descending RRF score.

## Why It Works

RRF is robust because it relies only on rank position, not on the absolute
scores from individual retrievers. This matters because:

- Vector similarity scores (cosine distances) and BM25 scores are on
  completely different scales and cannot be meaningfully averaged.
- Different queries may produce score distributions with different spreads;
  rank-based fusion is invariant to these scale differences.

The `k = 60` constant was empirically found to reduce the sensitivity of the
formula to particularly high-ranked outliers. It prevents a single top-ranked
result from dominating the fused score.

## Implementation

```python
from collections import defaultdict

def reciprocal_rank_fusion(result_lists: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranked_list in result_lists:
        for rank, doc_id in enumerate(ranked_list, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return sorted(scores, key=lambda d: scores[d], reverse=True)
```

## Comparison with Score Normalization

An alternative to RRF is min-max normalizing each retriever's scores to
[0, 1] and then taking a weighted sum. This approach is more sensitive to
tuning: the normalization range depends on the query, and the optimal weights
differ across domains. RRF avoids all of this with no training or tuning.

## RRF with More than Two Lists

RRF generalizes naturally to more than two retrieval lists. In a system with
vector search, keyword search, and a third retrieval method (e.g., sparse
semantic search or a knowledge graph lookup), all three lists can be fused
with the same formula. More lists generally improve recall coverage.

## Limitations

- RRF does not distinguish between a result at rank 1 vs. rank 2 by much when
  `k = 60`: `1/61` vs `1/62`. The smoothing means only the top ~5 results per
  list strongly influence the fused ranking.
- RRF is not a learned model. For workloads with enough labeled data, a learned
  fusion model (e.g., linear combination or LambdaMART) can outperform RRF by
  adapting to query type.

## Usage in RAG Systems

In RAG pipelines, RRF is applied after vector search and keyword search return
their candidate sets (typically top-20 each). The fused top-K documents (e.g.,
top-10) are then passed to a cross-encoder reranker for final ordering before
being inserted into the LLM context.
