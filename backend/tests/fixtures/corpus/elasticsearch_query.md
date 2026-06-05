# Elasticsearch Query DSL

Elasticsearch exposes its search capabilities through a JSON-based Query DSL
(Domain Specific Language). Understanding the query layer is essential for
building accurate, performant search applications on top of Elasticsearch or
OpenSearch (its open-source fork).

## Leaf Queries vs. Compound Queries

**Leaf queries** match against specific fields:
- `match` — full-text search with analysis (tokenization, stemming).
- `term` — exact match against a keyword (no analysis).
- `range` — numeric or date range filter.
- `match_phrase` — requires terms to appear in order.

**Compound queries** combine leaf queries:
- `bool` — the most common compound query; supports `must`, `should`,
  `must_not`, and `filter` clauses.
- `dis_max` — returns the maximum score across sub-queries.
- `function_score` — modifies relevance scores with custom functions
  (e.g., decay by date, boost by popularity).

## The bool Query

```json
{
  "query": {
    "bool": {
      "must": [
        { "match": { "content": "vector similarity search" } }
      ],
      "filter": [
        { "term": { "status": "published" } },
        { "range": { "created_at": { "gte": "2024-01-01" } } }
      ],
      "should": [
        { "match": { "title": "approximate nearest neighbor" } }
      ],
      "minimum_should_match": 0
    }
  }
}
```

`must` clauses affect relevance scores. `filter` clauses are cached and
binary (match or not) — they do not affect scoring.

## BM25 in Elasticsearch

Elasticsearch uses BM25 as its default similarity function, replacing the
older TF-IDF scoring that was default before version 5. The `k1` and `b`
parameters can be set per-index in the `similarity` settings block.

## Knn Search for Vectors

Recent versions added native k-NN search:

```json
{
  "knn": {
    "field": "embedding",
    "query_vector": [0.1, 0.2, ...],
    "k": 10,
    "num_candidates": 100
  }
}
```

The `num_candidates` parameter controls recall vs. latency, analogous to
`ef_search` in HNSW. Elasticsearch uses HNSW internally for vector indexes.

## Hybrid Search

Elasticsearch supports hybrid retrieval by combining `knn` and `query` in
the same request, then using Reciprocal Rank Fusion to merge result lists.
This matches the retrieval pattern used in modern RAG systems.

## Relevance Debugging

The `_explain` API returns a full breakdown of how a score was computed for
a given document, showing TF, IDF, and field-level boosts. This is
invaluable for tuning retrieval quality.
