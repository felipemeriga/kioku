-- Current, source-linked learnings. The daily Markdown remains the history.
CREATE TABLE public.repo_learnings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    topic_key text NOT NULL,
    statement text NOT NULL,
    status text NOT NULL CHECK (status IN ('reported', 'committed', 'retired')),
    source_entries jsonb NOT NULL DEFAULT '[]'::jsonb,
    git_sha text,
    reviewed_head_sha text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, folder_id, topic_key)
);
CREATE INDEX repo_learnings_folder_idx ON public.repo_learnings (user_id, folder_id, updated_at DESC);
ALTER TABLE public.repo_learnings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own repo learnings" ON public.repo_learnings
    FOR SELECT TO authenticated USING (auth.uid() = user_id);
REVOKE ALL ON public.repo_learnings FROM anon, authenticated;
GRANT SELECT ON public.repo_learnings TO authenticated;
GRANT ALL ON public.repo_learnings TO service_role;

-- One checkpoint per day. Entry IDs prevent reprocessing after a same-day upsert.
CREATE TABLE public.repo_learning_days (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    journal_date date NOT NULL,
    revision bigint NOT NULL,
    processed_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, folder_id, journal_date)
);
ALTER TABLE public.repo_learning_days ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.repo_learning_days FROM anon, authenticated;
GRANT ALL ON public.repo_learning_days TO service_role;
