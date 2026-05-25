# BM25: Best Match 25

BM25 (Best Match 25) is a probabilistic relevance ranking function widely used
in full-text search engines. It is the default ranking algorithm in
Elasticsearch, Lucene, and many other search systems. BM25 improved upon the
classic TF-IDF formula by addressing two well-known saturation problems.

## The Scoring Formula

For a query with terms `q1, q2, ..., qn` and document `D`, BM25 scores as:

```
score(D, Q) = sum over qi of:
  IDF(qi) * (tf(qi, D) * (k1 + 1)) / (tf(qi, D) + k1 * (1 - b + b * |D| / avgdl))
```

Where:
- `tf(qi, D)` is the term frequency of `qi` in document `D`.
- `|D|` is the document length in tokens.
- `avgdl` is the average document length in the corpus.
- `k1` is the term frequency saturation parameter (typically 1.2–2.0).
- `b` is the length normalization parameter (typically 0.75).
- `IDF(qi)` is the inverse document frequency of term `qi`.

## Key Improvements Over TF-IDF

**Term frequency saturation:** Raw TF gives unbounded score growth as term
frequency increases. BM25's denominator ensures that score growth plateaus —
adding the 1000th occurrence of a term contributes almost nothing beyond the
100th. The `k1` parameter controls how quickly this plateau is reached.

**Document length normalization:** BM25 penalizes long documents proportionally
to their length relative to the corpus average. This prevents long documents
from dominating results simply because they contain more words. The `b`
parameter controls how aggressively length is penalized (0 = no normalization,
1 = full normalization).

## IDF Weighting

BM25 uses a log-smoothed IDF: `log((N - df + 0.5) / (df + 0.5) + 1)` where N
is the number of documents and df is the number of documents containing the term.
This gives rare terms high weight and common terms (appearing in most documents)
weights close to zero.

## Limitations

BM25 is a bag-of-words model. It does not capture:
- Semantic meaning (synonyms, paraphrases)
- Word order or phrase proximity
- Cross-lingual similarity

For semantic retrieval, BM25 is typically combined with dense vector search in
a hybrid retrieval pipeline, with final results merged via Reciprocal Rank
Fusion or a learned ranker.

## Variants

- **BM25+** — adjusts the IDF to avoid negative weights for very common terms.
- **BM25F** — extends BM25 to field-structured documents (title, body, anchor),
  computing term frequencies per field with per-field boosts.
- **BM25L** — modifies length normalization for long documents where BM25's
  default under-counts term frequency.
