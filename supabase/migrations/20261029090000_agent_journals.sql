-- One active private Markdown journal per user, repository, and local day.
CREATE TABLE IF NOT EXISTS public.agent_journal_days (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    journal_date date NOT NULL,
    storage_path text NOT NULL,
    content_sha256 text NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    entry_count integer NOT NULL DEFAULT 0 CHECK (entry_count >= 0),
    agents text[] NOT NULL DEFAULT '{}',
    first_entry_at timestamptz,
    last_entry_at timestamptz,
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, folder_id, journal_date)
);

CREATE INDEX IF NOT EXISTS agent_journal_days_user_date_idx
    ON public.agent_journal_days (user_id, journal_date DESC);
ALTER TABLE public.agent_journal_days ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own agent journals" ON public.agent_journal_days
    FOR SELECT TO authenticated USING (auth.uid() = user_id);
REVOKE ALL ON public.agent_journal_days FROM anon, authenticated;
GRANT SELECT ON public.agent_journal_days TO authenticated;
GRANT ALL ON public.agent_journal_days TO service_role;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('agent-journals', 'agent-journals', false, 5242880, ARRAY['text/markdown'])
ON CONFLICT (id) DO NOTHING;

-- CAS is performed under a lock on the owning folder row. Upload the new
-- content-addressed object first, then publish its path atomically here.
CREATE OR REPLACE FUNCTION public.publish_agent_journal(
    p_user_id uuid, p_folder_id uuid, p_date date,
    p_expected_revision bigint, p_storage_path text, p_sha256 text,
    p_entry_count integer, p_agents text[],
    p_first_entry_at timestamptz, p_last_entry_at timestamptz
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_current public.agent_journal_days%ROWTYPE;
    v_revision bigint;
BEGIN
    PERFORM 1 FROM public.folders
    WHERE id = p_folder_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Repository not found for user'; END IF;

    SELECT * INTO v_current FROM public.agent_journal_days
    WHERE user_id = p_user_id AND folder_id = p_folder_id AND journal_date = p_date
    FOR UPDATE;
    IF FOUND AND v_current.content_sha256 = p_sha256 THEN
        RETURN jsonb_build_object('status', 'unchanged', 'revision', v_current.revision,
                                  'storage_path', v_current.storage_path);
    END IF;
    v_revision := COALESCE(v_current.revision, 0);
    IF v_revision <> p_expected_revision THEN
        RETURN jsonb_build_object('status', 'conflict', 'revision', v_revision,
                                  'storage_path', v_current.storage_path);
    END IF;

    INSERT INTO public.agent_journal_days AS j
        (user_id, folder_id, journal_date, storage_path, content_sha256,
         revision, entry_count, agents, first_entry_at, last_entry_at, synced_at)
    VALUES
        (p_user_id, p_folder_id, p_date, p_storage_path, p_sha256,
         v_revision + 1, p_entry_count, p_agents, p_first_entry_at, p_last_entry_at, now())
    ON CONFLICT (user_id, folder_id, journal_date) DO UPDATE SET
        storage_path = EXCLUDED.storage_path,
        content_sha256 = EXCLUDED.content_sha256,
        revision = EXCLUDED.revision,
        entry_count = EXCLUDED.entry_count,
        agents = EXCLUDED.agents,
        first_entry_at = EXCLUDED.first_entry_at,
        last_entry_at = EXCLUDED.last_entry_at,
        synced_at = now();
    RETURN jsonb_build_object('status', 'ok', 'revision', v_revision + 1,
                              'previous_path', v_current.storage_path,
                              'storage_path', p_storage_path);
END;
$$;
REVOKE ALL ON FUNCTION public.publish_agent_journal(uuid, uuid, date, bigint, text, text, integer, text[], timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.publish_agent_journal(uuid, uuid, date, bigint, text, text, integer, text[], timestamptz, timestamptz) TO service_role;
