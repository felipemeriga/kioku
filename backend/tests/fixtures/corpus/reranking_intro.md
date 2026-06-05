# Reranking: Cross-Encoder vs. Bi-Encoder

Retrieval systems typically operate in two stages: a fast first-stage retrieval
that recalls a large candidate set, followed by a slower second-stage reranking
that scores candidates more precisely. Understanding the tradeoff between
bi-encoders and cross-encoders is essential for designing effective RAG systems.

## Bi-Encoders (First Stage)

A bi-encoder encodes the query and each document independently into fixed-length
vectors. Similarity is computed as the dot product or cosine similarity of these
vectors. Because document embeddings can be precomputed and stored, bi-encoders
support fast approximate nearest neighbor search over large corpora.

Examples of bi-encoder models: all-MiniLM, voyage-3, text-embedding-3-large.

**Strengths:**
- Very fast at retrieval time (ANN search over precomputed embeddings).
- Scales to millions of documents with offline indexing.

**Weaknesses:**
- Each document is encoded without knowing the query. The model cannot attend
  to query-specific word senses.
- Recall@K is lower than a cross-encoder at the same K, particularly for
  queries with nuanced intent.

## Cross-Encoders (Second Stage)

A cross-encoder takes the query and document concatenated as a single input and
produces a relevance score. Because both texts are processed jointly, the model's
attention can capture fine-grained interactions between query terms and document
content.

Examples: Cohere Rerank, mixedbread-ai/mxbai-rerank, BCE-Reranker.

**Strengths:**
- Significantly higher precision than bi-encoders at the same candidate set.
- Captures query-document interactions that bi-encoders miss.

**Weaknesses:**
- Cannot precompute — every query requires a fresh forward pass over all
  candidates. This limits practical candidate set sizes to ~100–200 documents.
- Higher latency per query.

## Typical Pipeline

```
Query
  ↓
Bi-encoder ANN search → top 100 candidates (fast)
  ↓
Cross-encoder reranking → top 5 results (precise)
  ↓
LLM context window
```

The first stage provides recall coverage; the second stage provides precision.

## Cohere Rerank API

Cohere's managed reranking API accepts a query and a list of documents and
returns relevance scores:

```python
import cohere
co = cohere.Client()
results = co.rerank(
    model="rerank-english-v3.0",
    query="How does HNSW traverse layers?",
    documents=candidate_texts,
    top_n=5,
)
```

The returned scores are not probabilities but are monotonically ordered, so they
can be used directly for sorting.

## Latency Budget Considerations

Reranking adds 200–800 ms of latency depending on the number of candidates and
model size. For latency-sensitive applications, limit the reranker's candidate
set to 20–50 documents. For accuracy-critical applications, pass up to 100.
The first-stage recall@20 must be high enough that the correct answer is in
those 20 candidates before reranking begins.
