# Voyage AI Embedding Models

Voyage AI provides embedding models optimized for retrieval tasks. The
embedding API produces dense vector representations that can be used for
semantic search, clustering, and ranking in RAG pipelines.

## Model Overview

Voyage offers a range of models with different precision/cost tradeoffs:

- **voyage-3** — general-purpose retrieval model with 1024-dimensional output.
  Covers a wide range of domains including code, science, and finance.
- **voyage-3-lite** — smaller, faster, lower-cost version optimized for
  high-throughput batch embedding scenarios.
- **voyage-code-3** — specialized for code retrieval; achieves higher recall
  on code search benchmarks than general models.
- **voyage-3-large** — highest accuracy in the voyage-3 family, useful when
  retrieval precision is the primary concern.
- **voyage-finance-2**, **voyage-law-2** — domain-specialized models for
  financial and legal text, respectively.

## Input Types

The API accepts an `input_type` parameter that adjusts the embedding
toward query or document behavior:

- `"query"` — produces embeddings optimized for matching against documents.
  Use this for user queries.
- `"document"` — produces embeddings optimized for being retrieved.
  Use this when embedding corpus documents.

This asymmetric embedding design (sometimes called bi-encoder with input type
conditioning) typically improves retrieval quality compared to using a single
embedding function for both sides.

## API Usage

```python
import voyageai

client = voyageai.Client()

# Embed documents at ingestion time
doc_embeddings = client.embed(
    texts=["HNSW builds a multi-layer proximity graph..."],
    model="voyage-3",
    input_type="document"
).embeddings

# Embed query at search time
query_embedding = client.embed(
    texts=["How does HNSW search work?"],
    model="voyage-3",
    input_type="query"
).embeddings[0]
```

## Rate Limits and Batching

Voyage's paid tier has higher rate limits than the free tier. The API accepts
batches of up to 128 texts per request. For large corpora, embedding in
batches of 64–128 texts per request maximizes throughput without hitting
per-request token limits (which vary by model).

## Dimensionality and Storage

The `voyage-3` output dimension is 1024. At float32 precision this is 4 KB
per vector. For a 1-million document corpus with one embedding per document,
storage is ~4 GB. Using pgvector's `halfvec` type (float16) halves this to
~2 GB with minimal recall loss for cosine similarity search.

## Choosing a Model for RAG

For most general-purpose RAG workloads, `voyage-3` provides a strong
balance of quality, latency, and cost. Upgrade to `voyage-3-large` if your
golden set evaluation shows consistent retrieval failures. Use `voyage-3-lite`
if embedding cost is a bottleneck and your queries are relatively
unambiguous.
