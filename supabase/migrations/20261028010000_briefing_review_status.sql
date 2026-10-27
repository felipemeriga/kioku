ALTER TABLE public.repo_freshness
    ADD COLUMN IF NOT EXISTS section_reviews jsonb NOT NULL DEFAULT '{}'::jsonb;
