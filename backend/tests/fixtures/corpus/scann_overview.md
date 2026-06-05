# ScaNN: Scalable Nearest Neighbors

ScaNN (Scalable Nearest Neighbors) is a vector similarity search library from
Google Research designed for high-recall, high-throughput ANN search at
billion-vector scale. It uses a combination of space partitioning and learned
quantization to outperform most other libraries on standard ANN benchmarks.

## Core Algorithm

ScaNN operates in three stages:

1. **Partitioning** — vectors are assigned to clusters (similar to IVF).
   A query probes only the nearest clusters.
2. **Asymmetric hashing** — database vectors are compressed using anisotropic
   vector quantization (AVQ), which preferentially minimizes error in the
   direction most likely to affect ranking. This is the key innovation
   over standard product quantization.
3. **Rescoring** — top candidates from the hashed search are rescored using
   exact distances to produce the final result.

## Anisotropic Vector Quantization

Standard PQ minimizes reconstruction error uniformly across all dimensions.
AVQ instead weights the quantization error by a function of the inner product,
so that error in dimensions that most distinguish near from far neighbors is
penalized more. Empirically this gives significantly higher recall at the same
compression ratio, particularly for inner-product similarity (dot product).

## Performance

On the ANN-benchmarks suite (ann-benchmarks.com), ScaNN consistently achieves
state-of-the-art recall at 10-ms latency for datasets like GloVe-100, SIFT-1M,
and deep-image-1B. At 90% recall@10, ScaNN often achieves 2–5x higher QPS
than FAISS IVF-PQ and 1.5–3x higher QPS than HNSW.

## Deployment

ScaNN is a C++ library with a Python wrapper. It is the backend for Google's
Vertex AI Vector Search (formerly Matching Engine). As a standalone library:

```python
import scann
searcher = scann.scann_ops_pybind.builder(db, 10, "dot_product") \
    .tree(num_leaves=2000, num_leaves_to_search=100) \
    .score_ah(2) \
    .reorder(100) \
    .build()
neighbors, distances = searcher.search(query)
```

## Limitations

- **Linux-only** official build (macOS requires building from source).
- **Immutable index** — no incremental updates without a rebuild.
- **Inner-product optimized** — works best with normalized vectors and
  dot-product similarity. Cosine search requires normalizing vectors first.

## When to Use ScaNN

ScaNN is the right choice when recall@10 at high QPS is the primary goal and
the infrastructure is Linux-based. It is overkill for corpora under a few
million vectors where HNSW provides excellent recall with simpler setup.
