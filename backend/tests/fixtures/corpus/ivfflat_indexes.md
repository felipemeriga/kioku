# IVFFlat: Inverted File Index with Flat Storage

IVFFlat (Inverted File with Flat vectors) is a partitioning-based approximate
nearest neighbor algorithm. It divides the vector space into a fixed number of
clusters (Voronoi cells) using k-means, then at query time probes only a
subset of those cells rather than scanning all vectors.

## Index Construction

1. Run k-means on a sample of the dataset to find `lists` centroids.
2. Assign each vector to its nearest centroid and store it in that cell's
   inverted list.
3. The "Flat" suffix means vectors are stored uncompressed. A variant called
   IVF-PQ stores quantized approximations to reduce memory use.

Building an IVFFlat index is much faster than HNSW because it only requires
a single k-means pass, which parallelizes well across cores.

## Query Execution

At query time:
1. Compute the distance from the query to all `lists` centroids.
2. Probe the `nprobe` closest cells.
3. Scan all vectors in those cells with brute force and return the top-k.

Recall improves monotonically with `nprobe`. At `nprobe == lists` the search
becomes exact (full scan). Typical production settings use `nprobe` between
10 and 100.

## Parameters

- `lists` — number of Voronoi cells. Recommended heuristic: `sqrt(N)` for
  datasets up to a few million vectors.
- `nprobe` — cells probed per query. The primary recall/latency knob.
  Default in pgvector is 1, which is very low for real workloads.

## pgvector Usage

```sql
CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

SET ivfflat.probes = 10;
SELECT * FROM documents ORDER BY embedding <=> '[...]' LIMIT 5;
```

The `SET` statement is session-scoped. For production, set `ivfflat.probes`
in your connection pool or use `ALTER SYSTEM`.

## Tradeoffs vs. HNSW

IVFFlat has lower memory overhead than HNSW because it stores only raw
vectors plus a small centroid table. However, its recall at low `nprobe`
values degrades more sharply, particularly in high-dimensional spaces
(>= 512 dims) where cluster boundaries become less meaningful.

## When to Use IVFFlat

Prefer IVFFlat when memory is constrained, when the full dataset can be
loaded at once for a batch index build, or when you need a fast initial
prototype. For datasets under ~100k vectors it often performs comparably to
HNSW. For recall-sensitive production systems above 1M vectors, HNSW
usually wins on latency.
