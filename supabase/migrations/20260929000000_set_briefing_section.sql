-- Atomic single-section briefing update.
--
-- The watcher refreshes several sections per pass (activity + dependencies +
-- deployment + …), each as its own request. The old path read the whole
-- `content`, changed one section, and wrote the whole `content` back — so two
-- near-simultaneous refreshes raced: the second read could miss the first's
-- just-committed section and clobber it on write (observed: a dependencies
-- refresh reverting an activity refresh a second earlier).
--
-- This function updates ONLY the one section's jsonb path on the latest
-- briefing row, under the row lock, so concurrent section refreshes compose
-- instead of overwriting each other.
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
    SET content = jsonb_set(
        COALESCE(content, '{}'::jsonb),
        ARRAY['sections', p_section],
        p_value,
        true
    )
    WHERE id = v_id;
    RETURN true;
END;
$$;
