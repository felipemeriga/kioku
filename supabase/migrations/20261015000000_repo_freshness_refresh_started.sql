-- Track when an on-demand refresh (code index / detail sections) was triggered,
-- so the Status tab can show a persistent "refreshing" state across page reloads
-- (the watcher only reports in-progress via a 409; nothing was queryable before).
-- The watcher's repo_freshness upsert uses merge-duplicates and never writes
-- these columns, so it won't clobber them.
ALTER TABLE public.repo_freshness
  ADD COLUMN IF NOT EXISTS index_refresh_started_at timestamp with time zone,
  ADD COLUMN IF NOT EXISTS sections_refresh_started_at timestamp with time zone;
