BEGIN;
INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000001');
INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
VALUES('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','learnings',repeat('a',40),'d','learning','{"expected_sections":{},"current":[],"learning_day":{"journal_date":"2026-11-04","revision":1,"prior":{},"all_ids":["entry1"]},"input":{"main_commits":[],"new_entries":[{"id":"entry1","date":"2026-11-04","agent":"codex","text":"Section updates use a serialized folder lock."}]}}','{}');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
SELECT '30000000-0000-0000-0000-000000000002',user_id,folder_id,operation,head_sha,input_digest,'stale',snapshot,request FROM maintenance_preparations;
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','job-learning','{"updates":[{"topic_key":"folder-lock","statement":"Section writes use the folder lock.","source_ids":["entry1"],"evidence_quote":"serialized folder lock","git_sha":null,"retire":false}]}');
DO $$ BEGIN
 IF (SELECT count(*) FROM repo_learnings)<>1 THEN RAISE EXCEPTION 'learning missing'; END IF;
 IF (SELECT revision FROM repo_learning_days)<>1 THEN RAISE EXCEPTION 'learning checkpoint not advanced'; END IF;
 IF (SELECT source_entries->0->>'id' FROM repo_learnings)<>'entry1' THEN RAISE EXCEPTION 'source provenance missing'; END IF;
 BEGIN
  PERFORM apply_maintenance_result('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','job-stale-learning','{"updates":[]}');
  RAISE EXCEPTION 'stale checkpoint accepted';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM<>'stale learning checkpoint' THEN RAISE; END IF;
 END;
END $$;
ROLLBACK;
