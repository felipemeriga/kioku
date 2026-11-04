-- Run after schema + real migrations, inside an isolated fixture database.
BEGIN;
INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000001');
INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo');
INSERT INTO folder_summaries(folder_id,user_id,kind,content,sections) VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo','{"sections":{"activity":{"content":{"summary":"Old","highlights":["Old"]}}}}','{"activity":{"content":{"summary":"Old","highlights":["Old"]}}}');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
VALUES('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','review_plan',repeat('a',40),'digest','plan','{"expected_sections":{"activity":{"content":{"summary":"Old","highlights":["Old"]}}},"documentation_revision":null}','{}');
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','job-plan','{"selected":["activity"]}');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
VALUES('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','activity',repeat('a',40),'digest','activity','{"expected_sections":{"activity":{"content":{"summary":"Old","highlights":["Old"]}}}}','{}');
-- Concurrent preparation snapshots the same old content before publication.
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request,created_at,execution_job_id,publication) SELECT '30000000-0000-0000-0000-000000000003',user_id,folder_id,operation,head_sha,input_digest,'stale',snapshot,request,created_at,NULL,NULL FROM maintenance_preparations WHERE id='30000000-0000-0000-0000-000000000002';
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','job-activity','{"summary":"New","highlights":["New"]}');
DO $$
DECLARE n integer; r jsonb;
BEGIN
    SELECT count(*) INTO n FROM folder_summaries;
    IF n<>2 THEN RAISE EXCEPTION 'expected exactly one new snapshot'; END IF;
    SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','job-activity','{"summary":"INJECTED","highlights":[]}') INTO r;
    IF NOT (r->>'updated')::boolean OR (SELECT count(*) FROM folder_summaries)<>2 THEN RAISE EXCEPTION 'duplicate publish was not idempotent'; END IF;
    BEGIN
        PERFORM apply_maintenance_result('30000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','job-stale','{"summary":"Stale","highlights":["Stale"]}');
        RAISE EXCEPTION 'stale CAS accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM NOT LIKE 'stale section revision:%' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM apply_maintenance_result('30000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000099','job-owner','{}');
        RAISE EXCEPTION 'foreign owner accepted';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM<>'unknown preparation' THEN RAISE; END IF;
    END;
    IF NOT (SELECT acknowledged @> selected FROM maintenance_review_passes) THEN RAISE EXCEPTION 'pass not acknowledged'; END IF;
    IF NOT (SELECT section_reviews->'activity'->>'head_sha'=repeat('a',40) FROM repo_freshness) THEN RAISE EXCEPTION 'missing reviewed marker'; END IF;
END $$;
-- Valid unchanged outputs update review evidence without creating content versions.
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
SELECT '30000000-0000-0000-0000-000000000004',user_id,folder_id,'activity',repeat('b',40),'d','unchanged',jsonb_build_object('expected_sections',sections),'{}' FROM folder_summaries ORDER BY generated_at DESC LIMIT 1;
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000001','job-unchanged','{"summary":"New","highlights":["New"]}');
DO $$ BEGIN
 IF (SELECT count(*) FROM folder_summaries)<>2 THEN RAISE EXCEPTION 'unchanged content created a version'; END IF;
 IF NOT (SELECT section_reviews->'activity'->>'head_sha'=repeat('b',40) FROM repo_freshness) THEN RAISE EXCEPTION 'unchanged content not reviewed'; END IF;
END $$;
ROLLBACK;
