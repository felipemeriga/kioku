-- A full-body edit below the unchanged abstract must update publication metadata.
BEGIN;
SET LOCAL ROLE service_role;
INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000001');
INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo');
DO $$
DECLARE
    owner_id uuid := '10000000-0000-0000-0000-000000000001';
    folder_id uuid := '20000000-0000-0000-0000-000000000001';
    old_doc uuid := '40000000-0000-0000-0000-000000000001';
    first_prep uuid := '30000000-0000-0000-0000-000000000001';
    same_prep uuid := '30000000-0000-0000-0000-000000000002';
    stale_prep uuid := '30000000-0000-0000-0000-000000000003';
    ui_prep uuid := '30000000-0000-0000-0000-000000000004';
    intro text := repeat('An unchanged verified introduction. ',45);
    before_body text;
    after_body text;
    pointer text;
    baseline jsonb;
    current_sections jsonb;
    result jsonb;
    new_doc uuid;
    changed_at text;
    summaries_count integer;
    documents_count integer;
BEGIN
    before_body:=intro || E'\n\nDefault polling interval is 15 seconds.';
    after_body:=intro || E'\n\nDefault polling interval is 20 seconds.';
    pointer:=left(intro,900) || E'\n\nFull architecture docs available — call get_repo_documentation.';
    baseline:=jsonb_build_object('documentation',jsonb_build_object('content',pointer,'status','auto','provenance','agent_mcp','updated_by','agent_mcp','updated_at','2000-01-01T00:00:00Z')) || jsonb_build_object('overview',jsonb_build_object('content','Unchanged overview'));
    INSERT INTO folder_summaries(folder_id,user_id,kind,content,sections)
    VALUES(folder_id,owner_id,'repo',jsonb_build_object('sections',baseline),baseline);
    -- A prior writer may have a later timestamp than this transaction start
    -- (or a future wall-clock value). The new committed body must still be latest.
    INSERT INTO repo_documentation(id,folder_id,user_id,content,abstract,generated_at) VALUES(old_doc,folder_id,owner_id,before_body,left(intro,900),now() + interval '1 day');
    INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
    VALUES(first_prep,owner_id,folder_id,'documentation',repeat('a',40),'input','body-only',jsonb_build_object('expected_sections',baseline,'documentation_revision',old_doc,'current',jsonb_build_object('content',before_body)),'{"caller":"mihari"}');
    INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request) SELECT stale_prep,p.user_id,p.folder_id,p.operation,p.head_sha,p.input_digest,'stale-body',p.snapshot,p.request FROM maintenance_preparations p WHERE p.id=first_prep;
    result:=apply_maintenance_result(first_prep,owner_id,'job-body',jsonb_build_object('content',after_body));
    IF result->>'updated' IS DISTINCT FROM 'true' THEN RAISE EXCEPTION 'body-only edit falsely reported unchanged'; END IF;
    SELECT id INTO new_doc FROM repo_documentation ORDER BY generated_at DESC LIMIT 1;
    IF new_doc=old_doc OR (SELECT count(*) FROM repo_documentation)<>2 THEN RAISE EXCEPTION 'body not published exactly once'; END IF;
    IF (SELECT generated_at FROM repo_documentation WHERE id=new_doc) <= (SELECT generated_at FROM repo_documentation WHERE id=old_doc) THEN RAISE EXCEPTION 'new document did not advance latest revision timestamp'; END IF;
    SELECT sections INTO current_sections FROM folder_summaries ORDER BY generated_at DESC LIMIT 1;
    IF current_sections->'documentation'->>'content' IS DISTINCT FROM pointer THEN RAISE EXCEPTION 'unchanged abstract was modified'; END IF;
    IF current_sections->'documentation'->>'updated_by' IS DISTINCT FROM 'mihari' OR current_sections->'documentation'->>'provenance' IS DISTINCT FROM 'auto' THEN RAISE EXCEPTION 'body publication provenance not advanced'; END IF;
    changed_at:=current_sections->'documentation'->>'updated_at';
    IF changed_at IS NULL OR changed_at='2000-01-01T00:00:00Z' THEN RAISE EXCEPTION 'body modification time not advanced'; END IF;
    IF current_sections->'documentation'->>'document_revision' IS DISTINCT FROM new_doc::text THEN RAISE EXCEPTION 'body revision missing from section metadata'; END IF;
    IF (SELECT count(*) FROM folder_summaries)<>2 THEN RAISE EXCEPTION 'body edit did not make exactly one section write'; END IF;
    IF apply_maintenance_result(first_prep,owner_id,'job-body',jsonb_build_object('content','different replay text'))<>result THEN RAISE EXCEPTION 'replay publication not idempotent'; END IF;
    IF (SELECT count(*) FROM repo_documentation)<>2 OR (SELECT count(*) FROM maintenance_runner_ack_outbox WHERE job_id='job-body')<>1 THEN RAISE EXCEPTION 'replay duplicated body or acknowledgement'; END IF;
    BEGIN
        PERFORM apply_maintenance_result(stale_prep,owner_id,'job-stale',jsonb_build_object('content',before_body));
        RAISE EXCEPTION 'stale source accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM NOT LIKE 'stale section revision:%' THEN RAISE; END IF;
    END;
    INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
    VALUES(same_prep,owner_id,folder_id,'documentation',repeat('b',40),'input','unchanged-body',jsonb_build_object('expected_sections',jsonb_build_object('documentation',current_sections->'documentation'),'documentation_revision',new_doc,'current',jsonb_build_object('content',after_body)),'{"caller":"mihari"}');
    SELECT count(*) INTO summaries_count FROM folder_summaries;
    result:=apply_maintenance_result(same_prep,owner_id,'job-unchanged',jsonb_build_object('content',after_body));
    IF result->>'updated' IS DISTINCT FROM 'false' OR (SELECT count(*) FROM repo_documentation)<>2 OR (SELECT count(*) FROM folder_summaries)<>summaries_count THEN RAISE EXCEPTION 'unchanged body rewrote content'; END IF;
    IF (SELECT section_reviews->'documentation'->>'head_sha' FROM repo_freshness) IS DISTINCT FROM repeat('b',40) THEN RAISE EXCEPTION 'unchanged body not reviewed'; END IF;
    -- Same, malformed, historical and foreign references cannot manufacture freshness.
    PERFORM set_briefing_section(folder_id,owner_id,'documentation',(current_sections->'documentation') || '{"updated_at":"2099-01-01T00:00:00Z"}'::jsonb);
    PERFORM set_briefing_section(folder_id,owner_id,'documentation',(current_sections->'documentation') || '{"document_revision":"not-a-uuid","updated_at":"2099-01-01T00:00:00Z"}'::jsonb);
    PERFORM set_briefing_section(folder_id,owner_id,'documentation',(current_sections->'documentation') || jsonb_build_object('document_revision',old_doc,'updated_at','2099-01-01T00:00:00Z'));
    INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000002');
    INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','repo');
    INSERT INTO repo_documentation(id,user_id,folder_id,content,abstract) VALUES('40000000-0000-0000-0000-000000000099','10000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000002','Foreign guide','Foreign');
    PERFORM set_briefing_section(folder_id,owner_id,'documentation',(current_sections->'documentation') || '{"document_revision":"40000000-0000-0000-0000-000000000099","updated_at":"2099-01-01T00:00:00Z"}'::jsonb);
    INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000003',owner_id,'repo');
    INSERT INTO repo_documentation(id,user_id,folder_id,content,abstract) VALUES('40000000-0000-0000-0000-000000000098',owner_id,'20000000-0000-0000-0000-000000000003','Other folder guide','Other');
    PERFORM set_briefing_section(folder_id,owner_id,'documentation',(current_sections->'documentation') || '{"document_revision":"40000000-0000-0000-0000-000000000098","updated_at":"2099-01-01T00:00:00Z"}'::jsonb);
    PERFORM set_briefing_section(folder_id,owner_id,'overview',(current_sections->'overview') || jsonb_build_object('document_revision',new_doc));
    IF (SELECT count(*) FROM folder_summaries)<>summaries_count THEN RAISE EXCEPTION 'invalid or identical document reference manufactured freshness'; END IF;
    SELECT count(*) INTO documents_count FROM repo_documentation;
    -- User-owned content remains protected even when the full document differs.
    current_sections:=jsonb_set(current_sections,'{documentation,provenance}','"user_ui"');
    INSERT INTO folder_summaries(folder_id,user_id,kind,content,sections) VALUES(folder_id,owner_id,'repo',jsonb_build_object('sections',current_sections),current_sections);
    INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
    VALUES(ui_prep,owner_id,folder_id,'documentation',repeat('c',40),'input','ui-protected',jsonb_build_object('expected_sections',jsonb_build_object('documentation',current_sections->'documentation'),'documentation_revision',new_doc,'current',jsonb_build_object('content',after_body)),'{"caller":"mihari"}');
    BEGIN
        PERFORM apply_maintenance_result(ui_prep,owner_id,'job-ui',jsonb_build_object('content',before_body));
        RAISE EXCEPTION 'user UI document overwritten';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM <> 'user edited section' THEN RAISE; END IF;
    END;
    IF (SELECT count(*) FROM repo_documentation)<>documents_count THEN RAISE EXCEPTION 'blocked publication partially persisted'; END IF;
END $$;
ROLLBACK;
