-- Weight the document filename (A) above the body text (B) in the full-text
-- search vector. ts_rank's default weights favor A over B, so a query matching
-- a page/file title now ranks that document higher and filename-ish queries
-- recall their document even when the term is sparse in the body.
--
-- Redefining a GENERATED column requires drop + re-add (Postgres cannot alter
-- the generation expression in place). STORED means every existing row's fts is
-- recomputed on ADD, and the GIN index is rebuilt. No embeddings are touched.
-- keyword_search is unchanged: it already ranks with ts_rank(fts, query).

DROP INDEX IF EXISTS public.documents_fts_idx;

ALTER TABLE public.documents DROP COLUMN IF EXISTS fts;

ALTER TABLE public.documents
  ADD COLUMN fts tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(source_filename, '')), 'A') ||
    setweight(to_tsvector('english', content), 'B')
  ) STORED;

CREATE INDEX documents_fts_idx ON public.documents USING gin (fts);
