INSERT INTO tsukai_tool_traces(owner_id,job_id,attempt_id,folder_ids,trace,result)
VALUES('11111111-1111-1111-1111-111111111111','job-1','attempt-1',ARRAY['44444444-4444-4444-4444-444444444444']::uuid[],'{}','private source');
INSERT INTO documents VALUES(gen_random_uuid(),'11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','manual.pdf','pdf',now());
DO $$ BEGIN
  IF (tsukai_scoped_metadata('11111111-1111-1111-1111-111111111111',ARRAY['44444444-4444-4444-4444-444444444444']::uuid[],'count_files')->'data'->>'count')::integer <> 1 THEN
    RAISE EXCEPTION 'scoped file count incorrect'; END IF;
END $$;
DELETE FROM conversations WHERE id='33333333-3333-3333-3333-333333333333';
DO $$ BEGIN
  IF (SELECT count(*) FROM tsukai_domain_deletions WHERE kind='conversation') <> 1 THEN
    RAISE EXCEPTION 'conversation cleanup intent lost'; END IF;
  IF EXISTS(SELECT 1 FROM tsukai_tool_traces) OR EXISTS(SELECT 1 FROM tsukai_citation_sources) THEN
    RAISE EXCEPTION 'conversation evidence retained'; END IF;
END $$;
DELETE FROM auth.users WHERE id='11111111-1111-1111-1111-111111111111';
DO $$ BEGIN
  IF (SELECT count(*) FROM tsukai_domain_deletions WHERE kind='account') <> 1 THEN
    RAISE EXCEPTION 'account cleanup intent lost'; END IF;
END $$;
ROLLBACK;
