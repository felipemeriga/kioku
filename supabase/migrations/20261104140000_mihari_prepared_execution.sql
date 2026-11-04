-- Immutable evidence and compare-and-swap publication for both API and native
-- maintenance. Only service-role backend can prepare or publish jobs.
CREATE TABLE public.maintenance_preparations (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    operation text NOT NULL CHECK (operation IN ('review_plan','activity','how_it_runs','deployment','reground','documentation','learnings')),
    head_sha text NOT NULL,
    input_digest text NOT NULL,
    idempotency_key text NOT NULL,
    snapshot jsonb NOT NULL,
    request jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    execution_job_id text UNIQUE,
    publication jsonb,
    validation_error text,
    repair_of uuid REFERENCES public.maintenance_preparations(id),
    UNIQUE(user_id,idempotency_key)
);
ALTER TABLE public.maintenance_preparations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.maintenance_preparations FROM anon,authenticated;
GRANT ALL ON public.maintenance_preparations TO service_role;

CREATE TABLE public.maintenance_review_passes (
    folder_id uuid PRIMARY KEY REFERENCES public.folders(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    preparation_id uuid NOT NULL REFERENCES public.maintenance_preparations(id),
    head_sha text NOT NULL,
    selected jsonb NOT NULL,
    reviewed jsonb NOT NULL,
    acknowledged jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL
);
ALTER TABLE public.maintenance_review_passes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.maintenance_review_passes FROM anon,authenticated;
GRANT ALL ON public.maintenance_review_passes TO service_role;

CREATE OR REPLACE FUNCTION public.apply_maintenance_result(
    p_preparation uuid,p_user uuid,p_job text,p_value jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public AS $$
DECLARE
    prep public.maintenance_preparations;
    pass public.maintenance_review_passes;
    latest public.folder_summaries;
    sections jsonb;
    expected jsonb;
    updates jsonb := '{}';
    response jsonb;
    marker jsonb;
    section_name text;
    section_value jsonb;
    old_doc uuid;
    new_abstract text;
    entry jsonb;
    learning jsonb;
    old_learning public.repo_learnings;
    cited jsonb;
    known_ids jsonb;
    day jsonb;
    checkpoint public.repo_learning_days;
    updated_count integer := 0;
    promoted_count integer := 0;
BEGIN
    SELECT * INTO prep FROM maintenance_preparations WHERE id=p_preparation AND user_id=p_user FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'unknown preparation'; END IF;
    IF prep.execution_job_id IS NOT NULL THEN
        IF prep.execution_job_id <> p_job THEN RAISE EXCEPTION 'execution already bound'; END IF;
        RETURN prep.publication;
    END IF;
    PERFORM 1 FROM folders WHERE id=prep.folder_id AND user_id=p_user AND kind='repo' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'repository owner mismatch'; END IF;
    SELECT * INTO pass FROM maintenance_review_passes WHERE folder_id=prep.folder_id;
    IF FOUND AND pass.created_at>prep.created_at AND pass.head_sha<>prep.head_sha THEN
        RAISE EXCEPTION 'stale maintenance pass';
    END IF;
    -- The folder lock serializes with every legacy/UI briefing writer.
    SELECT * INTO latest FROM folder_summaries WHERE folder_id=prep.folder_id AND user_id=p_user ORDER BY generated_at DESC LIMIT 1;
    sections:=COALESCE(latest.sections,'{}') || COALESCE(latest.content->'sections','{}');
    expected:=prep.snapshot->'expected_sections';
    FOR section_name,section_value IN SELECT key,value FROM jsonb_each(expected) LOOP
        IF (sections->section_name) IS DISTINCT FROM section_value THEN
            RAISE EXCEPTION 'stale section revision: %', section_name;
        END IF;
        IF section_value->>'provenance'='user_ui' AND prep.operation<>'review_plan' THEN
            RAISE EXCEPTION 'user edited section';
        END IF;
    END LOOP;
    FOR section_name,section_value IN SELECT key,value FROM jsonb_each(COALESCE(prep.snapshot->'expected_reviews','{}')) LOOP
        IF COALESCE((SELECT section_reviews->section_name FROM repo_freshness WHERE folder_id=prep.folder_id),'null'::jsonb) IS DISTINCT FROM section_value THEN
            RAISE EXCEPTION 'stale section review: %',section_name;
        END IF;
    END LOOP;
    IF prep.operation IN ('documentation','review_plan') THEN
        SELECT id INTO old_doc FROM repo_documentation WHERE folder_id=prep.folder_id AND user_id=p_user ORDER BY generated_at DESC LIMIT 1;
        IF to_jsonb(old_doc) IS DISTINCT FROM NULLIF(prep.snapshot->'documentation_revision','null'::jsonb) THEN
            RAISE EXCEPTION 'stale documentation revision';
        END IF;
    END IF;
    IF prep.operation='review_plan' THEN
        -- Older prepared plan cannot replace a newer plan for the same HEAD.
        IF pass.created_at>prep.created_at THEN RAISE EXCEPTION 'stale review plan'; END IF;
        INSERT INTO maintenance_review_passes(folder_id,user_id,preparation_id,head_sha,selected,reviewed,created_at)
        VALUES(prep.folder_id,p_user,prep.id,prep.head_sha,p_value->'selected',to_jsonb(ARRAY(SELECT jsonb_object_keys(sections))),prep.created_at)
        ON CONFLICT(folder_id) DO UPDATE SET preparation_id=excluded.preparation_id,head_sha=excluded.head_sha,selected=excluded.selected,reviewed=excluded.reviewed,acknowledged='[]',created_at=excluded.created_at;
        response:=jsonb_build_object('ok',true,'selected',p_value->'selected','reviewed',to_jsonb(ARRAY(SELECT jsonb_object_keys(sections))));
    ELSIF prep.operation='learnings' THEN
        day:=prep.snapshot->'learning_day';
        SELECT * INTO checkpoint FROM repo_learning_days WHERE user_id=p_user AND folder_id=prep.folder_id AND journal_date=(day->>'journal_date')::date FOR UPDATE;
        IF COALESCE(checkpoint.processed_ids,'[]'::jsonb) IS DISTINCT FROM COALESCE(day->'prior'->'processed_ids','[]'::jsonb)
            OR COALESCE(checkpoint.revision,0)<>COALESCE((day->'prior'->>'revision')::integer,0) THEN
            RAISE EXCEPTION 'stale learning checkpoint';
        END IF;
        FOR learning IN SELECT value FROM jsonb_array_elements(p_value->'updates') LOOP
            SELECT * INTO old_learning FROM repo_learnings WHERE user_id=p_user AND folder_id=prep.folder_id AND topic_key=learning->>'topic_key' FOR UPDATE;
            IF jsonb_build_object('topic_key',old_learning.topic_key,'statement',old_learning.statement,'status',old_learning.status,'source_entries',old_learning.source_entries)
                IS DISTINCT FROM COALESCE((SELECT value FROM jsonb_array_elements(prep.snapshot->'current') WHERE value->>'topic_key'=learning->>'topic_key'),jsonb_build_object('topic_key',NULL,'statement',NULL,'status',NULL,'source_entries',NULL)) THEN
                RAISE EXCEPTION 'stale learning topic';
            END IF;
            cited:='[]';
            FOR entry IN SELECT value FROM jsonb_array_elements(prep.snapshot->'input'->'new_entries') LOOP
                IF learning->'source_ids' ? (entry->>'id') THEN
                    cited:=cited || jsonb_build_array(jsonb_build_object('id',entry->>'id','date',entry->>'date','agent',entry->>'agent','quote',CASE WHEN position(learning->>'evidence_quote' IN entry->>'text')>0 THEN learning->>'evidence_quote' ELSE NULL END));
                END IF;
            END LOOP;
            INSERT INTO repo_learnings(user_id,folder_id,topic_key,statement,status,source_entries,git_sha,reviewed_head_sha,updated_at)
            VALUES(p_user,prep.folder_id,learning->>'topic_key',learning->>'statement',CASE WHEN (learning->>'retire')::boolean THEN 'retired' WHEN prep.snapshot->'input'->'main_commits' ? (learning->>'git_sha') THEN 'committed' ELSE 'reported' END,COALESCE(old_learning.source_entries,'[]') || cited,learning->>'git_sha',prep.head_sha,clock_timestamp())
            ON CONFLICT(user_id,folder_id,topic_key) DO UPDATE SET statement=excluded.statement,status=excluded.status,source_entries=excluded.source_entries,git_sha=excluded.git_sha,reviewed_head_sha=excluded.reviewed_head_sha,updated_at=excluded.updated_at;
            updated_count:=updated_count+1;
        END LOOP;
        known_ids:=COALESCE(day->'prior'->'processed_ids','[]') || to_jsonb(ARRAY(SELECT value->>'id' FROM jsonb_array_elements(prep.snapshot->'input'->'new_entries')));
        INSERT INTO repo_learning_days(user_id,folder_id,journal_date,revision,processed_ids,processed_at)
        VALUES(p_user,prep.folder_id,(day->>'journal_date')::date,CASE WHEN known_ids @> (day->'all_ids') THEN (day->>'revision')::integer ELSE 0 END,known_ids,clock_timestamp())
        ON CONFLICT(user_id,folder_id,journal_date) DO UPDATE SET revision=excluded.revision,processed_ids=excluded.processed_ids,processed_at=excluded.processed_at;
        UPDATE repo_learnings SET status='committed',reviewed_head_sha=prep.head_sha,updated_at=clock_timestamp()
        WHERE user_id=p_user AND folder_id=prep.folder_id AND status='reported' AND (prep.snapshot->'input'->'main_commits') ? git_sha;
        GET DIAGNOSTICS promoted_count = ROW_COUNT;
        updated_count:=updated_count+promoted_count;
        response:=jsonb_build_object('ok',true,'processed_entries',jsonb_array_length(prep.snapshot->'input'->'new_entries'),'updated_learnings',updated_count);
    ELSE
        IF prep.operation='reground' THEN updates:=p_value;
        ELSIF prep.operation='documentation' THEN
            -- Preserve the detailed document and its briefing pointer atomically.
            IF p_value->>'content' IS DISTINCT FROM prep.snapshot->'current'->>'content' THEN
                SELECT left(string_agg(trim(line),E'\n'),900) INTO new_abstract FROM regexp_split_to_table(p_value->>'content', E'\n') line WHERE trim(line)<>'' AND trim(line) NOT LIKE '#%' AND trim(line) NOT LIKE '```%';
                INSERT INTO repo_documentation(user_id,folder_id,content,abstract) VALUES(p_user,prep.folder_id,p_value->>'content',new_abstract);
                updates:=jsonb_build_object('documentation',new_abstract || E'\n\nFull architecture docs available — call get_repo_documentation.');
            END IF;
        ELSE updates:=jsonb_build_object(prep.operation,p_value);
        END IF;
        FOR section_name,section_value IN SELECT key,value FROM jsonb_each(updates) LOOP
            IF sections->section_name->'content' IS DISTINCT FROM section_value THEN
                PERFORM set_briefing_section(prep.folder_id,p_user,section_name,jsonb_build_object('content',section_value,'status','auto','provenance','auto','updated_by','mihari','updated_at',clock_timestamp()));
                updated_count:=updated_count+1;
            END IF;
        END LOOP;
        IF pass.folder_id IS NOT NULL AND pass.head_sha=prep.head_sha THEN
            UPDATE maintenance_review_passes SET acknowledged=acknowledged || CASE WHEN prep.operation='reground' THEN prep.snapshot->'input'->'selected' ELSE jsonb_build_array(prep.operation) END WHERE folder_id=prep.folder_id;
        END IF;
        marker:=jsonb_build_object('head_sha',prep.head_sha,'reviewed_at',clock_timestamp());
        INSERT INTO repo_freshness(folder_id,user_id,section_reviews) VALUES(prep.folder_id,p_user,COALESCE((SELECT jsonb_object_agg(key,marker) FROM jsonb_each(CASE WHEN prep.operation='reground' THEN updates ELSE jsonb_build_object(prep.operation,p_value) END)),'{}'))
        ON CONFLICT(folder_id) DO UPDATE SET section_reviews=repo_freshness.section_reviews || excluded.section_reviews;
        response:=jsonb_build_object('ok',true,'updated',updated_count>0,'section',prep.operation,'sections',to_jsonb(ARRAY(SELECT jsonb_object_keys(updates))));
    END IF;
    SELECT * INTO pass FROM maintenance_review_passes WHERE folder_id=prep.folder_id;
    IF pass.folder_id IS NOT NULL AND pass.head_sha=prep.head_sha AND pass.acknowledged @> pass.selected THEN
        marker:=jsonb_build_object('head_sha',prep.head_sha,'reviewed_at',clock_timestamp());
        INSERT INTO repo_freshness(folder_id,user_id,section_reviews) VALUES(prep.folder_id,p_user,COALESCE((SELECT jsonb_object_agg(value#>>'{}',marker) FROM jsonb_array_elements(pass.reviewed)),'{}'))
        ON CONFLICT(folder_id) DO UPDATE SET section_reviews=repo_freshness.section_reviews || excluded.section_reviews;
    END IF;
    UPDATE maintenance_preparations SET execution_job_id=p_job,publication=response WHERE id=prep.id;
    RETURN response;
END;
$$;
REVOKE ALL ON FUNCTION public.apply_maintenance_result(uuid,uuid,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.apply_maintenance_result(uuid,uuid,text,jsonb) TO service_role;
