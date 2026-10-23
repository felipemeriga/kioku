-- Job completion is independent of whether indexed content changed.
ALTER TABLE public.repo_freshness
  ADD COLUMN IF NOT EXISTS index_refresh_finished_at timestamptz,
  ADD COLUMN IF NOT EXISTS index_refresh_error text,
  ADD COLUMN IF NOT EXISTS sections_refresh_finished_at timestamptz,
  ADD COLUMN IF NOT EXISTS sections_refresh_error text;
