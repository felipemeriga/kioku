-- Missing detailed docs are inspected absence, not a request to generate them.
-- Heal an existing native review pass without re-running current model work.
CREATE OR REPLACE FUNCTION public.acknowledge_absent_mihari_documentation(
    p_folder_id uuid, p_user_id uuid, p_head_sha text
) RETURNS boolean LANGUAGE plpgsql SET search_path=public AS $$
DECLARE
    review_pass public.maintenance_review_passes;
    reviews jsonb;
    marker jsonb;
    absent_marker jsonb;
BEGIN
    PERFORM 1 FROM folders WHERE id=p_folder_id AND user_id=p_user_id AND kind='repo' FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO review_pass FROM maintenance_review_passes
    WHERE folder_id=p_folder_id AND user_id=p_user_id AND head_sha=p_head_sha FOR UPDATE;
    IF NOT FOUND OR NOT (review_pass.selected ? 'documentation') THEN RETURN false; END IF;
    -- The backend, not the caller/model, establishes that there is no document.
    IF EXISTS(SELECT 1 FROM repo_documentation WHERE folder_id=p_folder_id AND user_id=p_user_id) THEN
        RETURN false;
    END IF;
    IF NOT (review_pass.acknowledged ? 'documentation') THEN
        UPDATE maintenance_review_passes SET acknowledged=acknowledged || '["documentation"]'::jsonb
        WHERE folder_id=p_folder_id AND user_id=p_user_id;
        review_pass.acknowledged:=review_pass.acknowledged || '["documentation"]'::jsonb;
    END IF;
    marker:=jsonb_build_object('head_sha',p_head_sha,'reviewed_at',clock_timestamp());
    absent_marker:=marker || jsonb_build_object('reason','absent','document_exists',false);
    reviews:=jsonb_build_object('documentation',absent_marker);
    IF review_pass.acknowledged @> review_pass.selected THEN
        SELECT COALESCE(jsonb_object_agg(value#>>'{}',marker),'{}'::jsonb) || reviews INTO reviews
        FROM jsonb_array_elements(review_pass.reviewed);
    END IF;
    INSERT INTO repo_freshness(folder_id,user_id,section_reviews) VALUES(p_folder_id,p_user_id,reviews)
    ON CONFLICT(folder_id) DO UPDATE SET section_reviews=repo_freshness.section_reviews || excluded.section_reviews;
    RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION public.acknowledge_absent_mihari_documentation(uuid,uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.acknowledge_absent_mihari_documentation(uuid,uuid,text) TO service_role;
