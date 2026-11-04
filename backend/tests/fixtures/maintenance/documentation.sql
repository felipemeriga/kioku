BEGIN;
INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000001');
INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo');
INSERT INTO folder_summaries(folder_id,user_id,kind,content,sections) VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo','{"sections":{"documentation":{"content":"Old pointer"}}}','{"documentation":{"content":"Old pointer"}}');
INSERT INTO repo_documentation(id,user_id,folder_id,content,abstract) VALUES('40000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','Old guide','Old abstract');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
VALUES('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','documentation',repeat('a',40),'d','doc','{"expected_sections":{"documentation":{"content":"Old pointer"}},"documentation_revision":"40000000-0000-0000-0000-000000000001","current":{"content":"Old guide"}}','{}');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
SELECT '30000000-0000-0000-0000-000000000002',user_id,folder_id,operation,head_sha,input_digest,'stale',snapshot,request FROM maintenance_preparations;
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','job-doc','{"content":"New guide.\n\n# Components\nThe backend owns authorization."}');
DO $$ BEGIN
 IF (SELECT count(*) FROM repo_documentation)<>2 THEN RAISE EXCEPTION 'new guide missing'; END IF;
 IF (SELECT count(*) FROM folder_summaries)<>2 THEN RAISE EXCEPTION 'new pointer missing'; END IF;
 IF (SELECT sections->'documentation'->>'content' FROM folder_summaries ORDER BY generated_at DESC LIMIT 1) NOT LIKE 'New guide.%' THEN RAISE EXCEPTION 'pointer does not match guide'; END IF;
 BEGIN
  PERFORM apply_maintenance_result('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','job-stale-doc','{"content":"Stale guide"}');
  RAISE EXCEPTION 'stale document accepted';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM NOT LIKE 'stale section revision:%' THEN RAISE; END IF;
 END;
 IF (SELECT count(*) FROM repo_documentation)<>2 THEN RAISE EXCEPTION 'stale document partially published'; END IF;
END $$;
ROLLBACK;
