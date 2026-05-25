# HNSW: Hierarchical Navigable Small World

HNSW is a graph-based approximate nearest neighbor (ANN) algorithm widely used
in vector databases. It builds a multi-layer proximity graph where the top
layers are sparse long-range connections and the bottom layer connects every
indexed vector to its nearest neighbors.

## How Search Works

A query starts at a fixed entry point in the topmost (sparsest) layer and
greedily moves toward whichever neighbor is closest to the query vector.
When it can no longer improve within the current layer, it drops down to the
next layer and repeats the greedy walk using a larger candidate set. The
bottom layer returns the approximate k nearest neighbors.

This hierarchical descent is what makes HNSW fast: the sparse upper layers
skip large distances quickly, and the dense lower layer refines the result.

## Index Parameters

- `m` — the number of bidirectional links maintained per node during
  construction. Higher `m` increases recall and memory use. Typical range: 16–64.
- `ef_construction` — size of the dynamic candidate list during index build.
  Higher values produce a better graph at the cost of slower ingestion.
  Typical range: 100–400.
- `ef_search` — candidate list size at query time. Increasing it improves
  recall but raises query latency. Typical range: 40–200.

## Memory Footprint

Each node stores edges to `m` neighbors per layer, so memory grows linearly
with the number of vectors and `m`. A corpus of 1 million 1024-dimensional
float32 vectors already needs ~4 GB for raw embeddings; HNSW edge overhead
can add another 20–40% depending on `m`.

## Tradeoffs vs. IVFFlat

HNSW generally achieves higher query throughput than IVFFlat at the same
recall level, particularly for high-dimensional spaces. The cost is higher
memory and slower index build time, because edges must be selected and
inserted one vector at a time. IVFFlat, by contrast, can be built with a
single k-means pass and trades query quality at low `nprobe` settings.

## Deletions and Updates

HNSW does not natively support deletion. In practice, deleted vectors are
soft-deleted (marked invalid) and filtered at query time, but they still
occupy graph memory. A full rebuild is required to reclaim space.
pgvector's HNSW implementation follows this pattern.

## When to Use HNSW

Choose HNSW when query latency is the primary constraint and the index can
fit in RAM. It excels at online workloads where vectors are inserted
incrementally over time. Avoid it when the dataset far exceeds available
memory, when index freshness requires frequent mass deletes, or when build
time must be minimized.
