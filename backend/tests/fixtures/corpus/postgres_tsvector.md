# PostgreSQL Full-Text Search: tsvector and tsquery

PostgreSQL provides built-in full-text search via its `tsvector` and `tsquery`
types. This allows keyword search directly inside Postgres without an external
search engine, which is attractive for systems already using Postgres as their
primary database.

## tsvector: The Document Representation

`tsvector` is a sorted list of lexemes — normalized word stems with their
positions in the original document. Postgres uses a language-specific text
search configuration to stem words and filter stop words.

```sql
SELECT to_tsvector('english', 'Vector databases store high-dimensional embeddings');
-- Result: 'databas':2 'dimension':4 'embed':5 'high':3 'store':2 'vector':1
```

Positions are recorded to support phrase search. Weights (A, B, C, D) can be
assigned to lexemes to boost matches in high-importance fields like titles.

## tsquery: The Query Representation

`tsquery` represents a boolean query over lexemes. Common forms:

```sql
-- Conjunction (AND):
SELECT to_tsquery('english', 'vector & search');

-- Disjunction (OR):
SELECT to_tsquery('english', 'bm25 | tfidf');

-- Phrase (adjacent words):
SELECT phraseto_tsquery('english', 'approximate nearest neighbor');

-- Plain query (AND by default, handles user input safely):
SELECT plainto_tsquery('english', 'approximate nearest neighbor search');
```

## Matching and Ranking

The `@@` operator checks whether a `tsvector` matches a `tsquery`:

```sql
SELECT * FROM documents
WHERE to_tsvector('english', content) @@ plainto_tsquery('english', 'vector index');
```

Two built-in ranking functions are available:
- `ts_rank(tsvector, tsquery)` — rank based on term frequency and position.
- `ts_rank_cd(tsvector, tsquery)` — cover density ranking; rewards documents
  where query terms appear closer together.

## Persisting tsvector with GIN Indexes

For large tables, computing `to_tsvector` at query time is too slow. The
recommended approach is to store the vector in a generated column and index it:

```sql
ALTER TABLE documents ADD COLUMN tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

CREATE INDEX documents_tsv_idx ON documents USING GIN (tsv);
```

GIN (Generalized Inverted Index) is optimized for tsvector and supports fast
`@@` lookups.

## Relevance in Hybrid Search

In a hybrid RAG system, Postgres full-text search provides the keyword leg of
retrieval alongside pgvector's similarity search. Results from both legs can
be merged using Reciprocal Rank Fusion. Using Postgres for both avoids network
round trips to an external search engine and keeps the system simpler.

One limitation is that PostgreSQL's text search is less sophisticated than
Elasticsearch: it lacks field-level boosting (like BM25F), distributed sharding,
and the rich query DSL available in Lucene-based systems.
