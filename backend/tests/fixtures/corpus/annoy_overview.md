# Annoy: Approximate Nearest Neighbors Oh Yeah

Annoy is a C++ library with Python bindings developed at Spotify for fast
read-only approximate nearest neighbor search. It is designed for use cases
where the index is built once and then queried many times, often from multiple
processes simultaneously.

## Index Structure

Annoy builds a forest of random projection trees. Each tree is constructed by
recursively splitting the vector space with random hyperplanes until each
leaf contains at most a configured number of vectors. The same set of vectors
appears in all trees, but with different random splits, so trees collectively
cover different neighborhoods.

At query time, Annoy traverses all trees simultaneously using a priority queue
of candidate nodes, merging results and returning the top-k neighbors across
the forest. More trees = better recall, larger index.

## Key Parameters

- `n_trees` — number of trees to build. Increasing this raises recall and
  index size roughly linearly. Values between 10 and 100 are typical.
- `search_k` — nodes to inspect during query. Higher values improve recall
  at the cost of query latency. Default is `n_trees * k`.

## Memory-Mapped Files

A major feature is that Annoy indexes can be memory-mapped from disk. Multiple
processes can open the same `.ann` file simultaneously with no copying. This
makes Annoy practical for serving scenarios where many worker processes share
one large index without duplicating RAM.

## Limitations

- **No incremental updates.** Once built, the index is immutable. Adding new
  vectors requires a full rebuild.
- **No exact mode.** Annoy is always approximate. Exact brute-force search is
  not supported through the Annoy API.
- **Not well-suited for very high dimensions.** Random projection splits
  become less effective above ~1000 dimensions where the curse of
  dimensionality limits the quality of each split.

## Comparison with HNSW

Annoy is simpler to deploy (single file, no database) but has lower recall at
the same latency compared to HNSW in most benchmarks. HNSW's graph traversal
adapts dynamically to the data distribution, while random projection trees use
fixed splits that may not align with the density structure of real embeddings.

For read-heavy, static corpora where memory-mapping is a priority (e.g., an
embedding service running across many replicas), Annoy remains a practical
choice despite these limitations.

## Typical Use Cases

- Music recommendation at Spotify (original use case)
- Semantic similarity in static document corpora
- Offline evaluation pipelines where the index does not change
