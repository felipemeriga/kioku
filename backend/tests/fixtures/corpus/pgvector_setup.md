# pgvector: Vector Similarity Search in PostgreSQL

pgvector is a PostgreSQL extension that adds a native vector data type and
similarity search operators. It allows storing, indexing, and querying dense
embedding vectors directly in Postgres without a separate vector database.

## Installation

```sql
-- In Postgres (requires the extension to be installed in the server):
CREATE EXTENSION IF NOT EXISTS vector;
```

On managed Postgres services like Supabase, the extension is available by
default and can be enabled from the dashboard or via SQL.

## Data Types

- `vector(n)` — a fixed-length dense vector of n float32 values.
- `halfvec(n)` — half-precision (float16) version; half the storage, minor
  precision loss. Added in pgvector 0.7.
- `sparsevec(n)` — sparse vector storing only non-zero values, useful for
  BM25 or TF-IDF sparse representations.

## Similarity Operators

```sql
-- L2 (Euclidean) distance:
embedding <-> '[0.1, 0.2, ...]'

-- Cosine distance (1 - cosine similarity):
embedding <=> '[0.1, 0.2, ...]'

-- Inner product (negative dot product):
embedding <#> '[0.1, 0.2, ...]'
```

Use cosine distance for normalized embeddings (the typical case with modern
embedding models). Use inner product when embeddings are not normalized and
you want to reward magnitude.

## Creating Indexes

**HNSW (recommended for low-latency queries):**
```sql
CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```

**IVFFlat (lower memory, higher build speed):**
```sql
CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

Index parameters can be tuned at query time:
```sql
SET hnsw.ef_search = 100;
SET ivfflat.probes = 10;
```

## Hybrid Search Pattern

A common pattern combines pgvector cosine search with Postgres full-text
search in a single query using a CTE:

```sql
WITH vector_results AS (
  SELECT id, 1 - (embedding <=> $1) AS score
  FROM documents
  ORDER BY embedding <=> $1 LIMIT 20
),
keyword_results AS (
  SELECT id, ts_rank(tsv, plainto_tsquery('english', $2)) AS score
  FROM documents
  WHERE tsv @@ plainto_tsquery('english', $2)
  ORDER BY score DESC LIMIT 20
)
SELECT * FROM vector_results
UNION ALL
SELECT * FROM keyword_results;
```

The merged results are then re-ranked with a cross-encoder or fused with RRF.

## Filtering

Filters on metadata columns can be added to any vector search:

```sql
SELECT * FROM documents
WHERE user_id = $1 AND topic = $2
ORDER BY embedding <=> $3
LIMIT 10;
```

For HNSW, pre-filtering (WHERE before ORDER BY) is generally more efficient
than post-filtering when the filter is selective. When the filter is loose
(matches most rows), post-filtering after LIMIT is faster.

## pgvector in Supabase

Supabase exposes pgvector through its JavaScript and Python clients. The
`match_documents` RPC pattern is commonly used to encapsulate the vector
search query in a Postgres function, keeping embedding logic on the
server side and returning clean typed results to the client.
