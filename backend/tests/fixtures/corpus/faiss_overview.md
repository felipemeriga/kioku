# FAISS: Facebook AI Similarity Search

FAISS is an open-source library from Meta AI Research for efficient similarity
search and clustering of dense vectors. It provides a wide range of index types
ranging from exact brute-force to highly compressed approximate structures,
and includes both CPU and GPU implementations.

## Index Taxonomy

FAISS indexes are composed of two orthogonal choices:

**Coarse quantizer (partitioning):**
- `Flat` — no partitioning; brute-force over all vectors.
- `IVF` — inverted file with k-means centroids (same concept as IVFFlat).
- `HNSW` — HNSW graph used as the coarse quantizer for fast centroid lookup.

**Fine quantizer (compression):**
- `Flat` — store full-precision float32 vectors.
- `PQ` — product quantization; compresses each vector into a short code.
- `SQ` — scalar quantization; quantizes each dimension to 8-bit integers.

Common combinations: `IndexFlatL2`, `IndexIVFFlat`, `IndexIVFPQ`, `IndexHNSWFlat`.

## Product Quantization

PQ splits each vector into `m` sub-vectors and quantizes each independently
using a codebook of size `k*`. The result is a short code of `m` bytes that
approximates the original vector. Memory savings can be dramatic — a 1024-dim
float32 vector (4 KB) can be compressed to 32 bytes with PQ(32, 256).

The tradeoff is recall degradation. Asymmetric distance computation (ADC)
partially compensates by computing exact distances from the query to codebook
centroids, keeping query recall reasonable even with compressed database vectors.

## GPU Support

FAISS provides native CUDA implementations for its most common index types.
GPU indexes can be 10–100x faster than CPU for large batch queries. The
`index_cpu_to_gpu` helper moves an existing CPU index to a GPU with minimal
code changes.

## Integration Patterns

FAISS is typically used as an in-process library, not a server. Common patterns:

- Build offline, serialize with `faiss.write_index`, load at serving time.
- Use `IndexIDMap` to map FAISS internal IDs to external document IDs.
- Wrap with a lightweight HTTP server (e.g., Flask) to create a microservice.

## Comparison with pgvector

FAISS is faster for large-scale offline search workloads because it runs
entirely in memory with no SQL overhead. pgvector integrates vector search
directly into Postgres, enabling combined vector + metadata filtering in a
single query — a major advantage for production RAG systems where filters
on user_id, topic, or date are common.
