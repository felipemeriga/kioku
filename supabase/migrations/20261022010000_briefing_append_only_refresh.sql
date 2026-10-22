-- Watcher refreshes are versions too. Serialize section refreshes on the
-- owning folder so concurrent refreshes compose on the newest snapshot.
ALTER TABLE public.folder_summaries
    DROP CONSTRAINT IF EXISTS folder_summaries_trigger_check;
ALTER TABLE public.folder_summaries
    ADD CONSTRAINT folder_summaries_trigger_check CHECK (
        trigger IS NULL OR trigger IN (
            'cron_nightly', 'cron_weekly', 'manual', 'seed', 'edit', 'mcp_edit',
            'restore', 'refresh', 'rollup_bootstrap:manual',
            'rollup_bootstrap:cron_nightly', 'rollup_bootstrap:cron_weekly'
        )
    );

CREATE OR REPLACE FUNCTION public.set_briefing_section(
    p_folder_id uuid, p_user_id uuid, p_section text, p_value jsonb
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
    v_latest record;
    v_sections jsonb;
BEGIN
    PERFORM 1 FROM public.folders
    WHERE id = p_folder_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO v_latest FROM public.folder_summaries
    WHERE folder_id = p_folder_id AND user_id = p_user_id
    ORDER BY generated_at DESC LIMIT 1;
    IF NOT FOUND THEN RETURN false; END IF;
    v_sections := COALESCE(v_latest.content->'sections', '{}'::jsonb)
                  || COALESCE(v_latest.sections, '{}'::jsonb);
    IF (v_sections->p_section->'content') IS NOT DISTINCT FROM (p_value->'content') THEN
        RETURN true;
    END IF;
    v_sections := jsonb_set(v_sections, ARRAY[p_section], p_value, true);
    INSERT INTO public.folder_summaries (
        folder_id, user_id, kind, trigger, content, sections, briefing_schema_version, generated_at
    ) VALUES (
        p_folder_id, p_user_id, v_latest.kind, 'refresh',
        jsonb_set(v_latest.content, '{sections}', v_sections, true),
        v_sections, v_latest.briefing_schema_version,
        GREATEST(clock_timestamp(), v_latest.generated_at + interval '1 microsecond')
    );
    -- NULL content_hash is intentional: readers compute the canonical Python
    -- hash for legacy/SQL-written rows, avoiding divergent JSON serialization.
    RETURN true;
END;
$$;
