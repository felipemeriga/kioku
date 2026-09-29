-- Give the backend's role headroom for bursty vector inserts.
--
-- The embed worker (embed_code_chunks_task) inserts batches into the
-- HNSW-indexed code_chunks table. A first full code index of a large repo
-- queues thousands of vector rows at once; under that concurrency each
-- insert can take tens of seconds (per-row HNSW maintenance + contention).
-- service_role had no statement_timeout of its own, so it fell back to the
-- authenticator connection default (8s) and Postgres canceled the inserts
-- with `57014 canceling statement due to statement timeout` — only a
-- fraction of the chunks landed, leaving whole crates unsearchable.
--
-- 55s sits just under the Supabase client's 60s httpx read timeout (see
-- backend/db/client.py) so the DB fails cleanly before the client if a
-- statement ever truly runs away. Normal incremental indexing does small
-- inserts well under this; the headroom only matters for bulk backfills.
ALTER ROLE service_role SET statement_timeout = '55s';
NOTIFY pgrst, 'reload config';
