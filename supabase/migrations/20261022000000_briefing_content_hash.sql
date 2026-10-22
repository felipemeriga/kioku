-- Per-version content hash of a briefing's sections (content only). Enables the
-- dedup gate (skip writing an identical version) and powers the history view.
-- Nullable: legacy rows stay NULL and callers compute the hash on the fly.
ALTER TABLE public.folder_summaries ADD COLUMN IF NOT EXISTS content_hash text;
