-- Fix: set_briefing_section wrote only content.sections, but the read path
-- (routes/briefing.py::_current_briefing → get_latest_summary) reads the
-- TOP-LEVEL `sections` column first and only falls back to content.sections
-- for pre-migration rows. So every watcher write (activity + concrete
-- sections) landed in the fallback location the UI never reads — the folder
-- briefing kept showing the last agent-authored values (observed: c360-lead
-- activity stuck at agent_mcp/pinned while the watcher had refreshed it).
--
-- The canonical edit path (_persist_sections) writes BOTH the top-level
-- `sections` column and content.sections. This function now does the same,
-- atomically on the latest row under FOR UPDATE, so watcher refreshes are
-- visible and concurrent single-section writes still compose.
CREATE OR REPLACE FUNCTION "public"."set_briefing_section"(
    "p_folder_id" "uuid",
    "p_user_id" "uuid",
    "p_section" "text",
    "p_value" "jsonb"
) RETURNS boolean
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    v_id uuid;
BEGIN
    SELECT id INTO v_id
    FROM public.folder_summaries
    WHERE folder_id = p_folder_id AND user_id = p_user_id
    ORDER BY generated_at DESC
    LIMIT 1
    FOR UPDATE;
    IF v_id IS NULL THEN
        RETURN false;
    END IF;
    UPDATE public.folder_summaries
    SET sections = jsonb_set(
            COALESCE(sections, '{}'::jsonb),
            ARRAY[p_section],
            p_value,
            true
        ),
        content = jsonb_set(
            COALESCE(content, '{}'::jsonb),
            ARRAY['sections', p_section],
            p_value,
            true
        )
    WHERE id = v_id;
    RETURN true;
END;
$$;
