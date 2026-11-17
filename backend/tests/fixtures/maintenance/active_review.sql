-- Active planners do not depend on retired docs; explicit legacy CAS remains.
BEGIN;
SET LOCAL ROLE service_role;
INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000001');
INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo');
INSERT INTO folder_summaries(folder_id,user_id,kind,content,sections)
VALUES('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo','{}','{"overview":{"content":"Stable overview"}}');
INSERT INTO repo_documentation(folder_id,user_id,content,abstract) VALUES('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','Retired historical documentation','Legacy');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
VALUES('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','review_plan',repeat('a',40),'active','active-only','{"expected_sections":{"overview":{"content":"Stable overview"}},"expected_reviews":{}}','{}');
DO $$ DECLARE result jsonb; BEGIN
 result:=apply_maintenance_result('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','completed-job','{"selected":["activity"]}');
 IF result->>'ok'<>'true' THEN RAISE EXCEPTION 'active review failed with retired document'; END IF;
 IF apply_maintenance_result('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','completed-job','{"selected":[]}')<>result THEN RAISE EXCEPTION 'immutable replay changed'; END IF;
 INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
 VALUES('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','review_plan',repeat('a',40),'legacy','legacy-explicit','{"expected_sections":{},"documentation_revision":null}','{}');
 BEGIN
 PERFORM apply_maintenance_result('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','legacy-job','{"selected":[]}');
 RAISE EXCEPTION 'explicit document CAS bypassed';
 EXCEPTION WHEN raise_exception THEN IF SQLERRM<>'stale documentation revision' THEN RAISE; END IF; END;
END $$;
ROLLBACK;
