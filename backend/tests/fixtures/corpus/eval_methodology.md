# Evaluation Methodology for Information Retrieval

Rigorous evaluation of a retrieval system requires both an appropriate metric
and a methodology that produces stable, meaningful signals. This document
covers the standard IR metrics and how to apply them in a RAG context.

## Relevance Judgments

All IR metrics start from binary or graded relevance judgments: for each
(query, document) pair, a human assessor (or a judge LLM) rates whether the
document is relevant to the query.

- **Binary relevance:** 0 (not relevant) or 1 (relevant).
- **Graded relevance:** e.g., 0 (not relevant), 1 (somewhat relevant), 2
  (highly relevant). Used in NDCG.

Constructing a high-quality relevance judgment set is the most labor-intensive
part of building an eval harness.

## Precision@K

The fraction of retrieved documents in the top-K that are relevant.

```
Precision@K = (# relevant docs in top K) / K
```

If K = 5 and 3 of the top 5 are relevant, P@5 = 0.6. This metric does not
account for the position of relevant results within the top K.

## Recall@K

The fraction of all relevant documents that appear in the top-K results.

```
Recall@K = (# relevant docs in top K) / (total # relevant docs for query)
```

Recall@K is bounded by min(K, total_relevant) / total_relevant. For RAG, where
the LLM only sees a few retrieved chunks, Recall@5 or Recall@10 is often more
important than Precision — you can't answer the question if the right chunk
was never retrieved.

## Mean Reciprocal Rank (MRR)

MRR measures how high the first relevant result appears, averaged over all
queries.

```
MRR = (1 / |Q|) * sum over queries q of: 1 / rank(first relevant result for q)
```

If for query 1 the first relevant result is at rank 2, and for query 2 it is
at rank 1: MRR = 0.5 * (1/2 + 1/1) = 0.75.

MRR is appropriate when users care primarily about finding one good answer
quickly. It ignores everything beyond the first relevant result.

## NDCG@K (Normalized Discounted Cumulative Gain)

NDCG accounts for both relevance grade and rank position. Higher-relevance
results appearing higher in the list yield higher scores.

```
DCG@K = sum from i=1 to K of: (2^relevance_i - 1) / log2(i + 1)
NDCG@K = DCG@K / IDCG@K
```

Where IDCG is the ideal DCG (the best achievable DCG given the relevance
judgments). NDCG@K = 1.0 means the retriever returned results in perfect order.

## Choosing Metrics for RAG

| Metric      | Good for                                  |
|-------------|-------------------------------------------|
| Recall@K    | Ensuring the right chunk is in the context|
| Precision@K | Keeping irrelevant context out of LLM window|
| MRR         | Single-answer question answering          |
| NDCG@K      | Graded relevance, ranked quality assessment|

For most RAG systems, **Recall@5** and **Precision@5** are the primary metrics.
NDCG@10 is useful when you have graded relevance judgments and want a single
combined quality score.

## Regression Testing

The eval harness should track metric deltas across commits, not just
absolute scores. A 1-point drop in Recall@5 from 0.82 to 0.81 may be noise;
a 5-point drop after a chunking change is a signal worth investigating.
