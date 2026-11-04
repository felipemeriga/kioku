-- Forward-migration regressions. Exercise production service role, not table owner.
BEGIN;
SET LOCAL ROLE service_role;
INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000001');
INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo');
INSERT INTO folder_summaries(folder_id,user_id,kind,content,sections) VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo','{"sections":{"activity":{"content":{"summary":"Old","highlights":["Old"]}},"deployment":{"content":{"environments":[],"how_to_deploy":"Old","ci_cd_notes":"Old"}}}}','{"activity":{"content":{"summary":"Old","highlights":["Old"]}},"deployment":{"content":{"environments":[],"how_to_deploy":"Old","ci_cd_notes":"Old"}}}');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
SELECT '30000000-0000-0000-0000-000000000001',user_id,folder_id,'review_plan',repeat('a',40),'d','plan1',jsonb_build_object('expected_sections',sections,'documentation_revision',null),'{}' FROM folder_summaries;
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','job-plan1','{"selected":["activity","deployment"]}');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
SELECT '30000000-0000-0000-0000-000000000002',user_id,folder_id,'activity',repeat('a',40),'d','activity',jsonb_build_object('expected_sections',jsonb_build_object('activity',sections->'activity')),'{"caller":"mihari"}' FROM folder_summaries;
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000001','job-activity','{"summary":"New","highlights":["New"]}');
DO $$ BEGIN
 IF (SELECT acknowledged @> selected FROM maintenance_review_passes) THEN RAISE EXCEPTION 'partial pass incorrectly complete'; END IF;
 IF (SELECT acknowledged_at FROM maintenance_runner_ack_outbox WHERE job_id='job-activity') IS NOT NULL THEN RAISE EXCEPTION 'publication prematurely acknowledged'; END IF;
END $$;
-- Deployment failed. A new plan is generated from the changed snapshot on retry.
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
SELECT '30000000-0000-0000-0000-000000000003',user_id,folder_id,'review_plan',repeat('a',40),'d','plan2',jsonb_build_object('expected_sections',sections,'documentation_revision',null),'{}' FROM folder_summaries ORDER BY generated_at DESC LIMIT 1;
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000001','job-plan2','{"selected":["activity","deployment"]}');
DO $$ BEGIN
 IF NOT (SELECT acknowledged ? 'activity' FROM maintenance_review_passes) THEN RAISE EXCEPTION 'same-HEAD completed activity lost acknowledgement'; END IF;
 IF (SELECT acknowledged ? 'deployment' FROM maintenance_review_passes) THEN RAISE EXCEPTION 'failed deployment was acknowledged'; END IF;
END $$;
-- Activity is skipped without a model call; deployment alone now completes the pass.
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
SELECT '30000000-0000-0000-0000-000000000004',user_id,folder_id,'deployment',repeat('a',40),'d','deployment',jsonb_build_object('expected_sections',jsonb_build_object('deployment',sections->'deployment')),'{"caller":"mihari"}' FROM folder_summaries ORDER BY generated_at DESC LIMIT 1;
SELECT apply_maintenance_result('30000000-0000-0000-0000-000000000004','10000000-0000-0000-0000-000000000001','job-deployment','{"environments":["Production"],"how_to_deploy":"New","ci_cd_notes":"New"}');
DO $$ BEGIN
 IF NOT (SELECT acknowledged @> selected FROM maintenance_review_passes) THEN RAISE EXCEPTION 'retried pass cannot complete'; END IF;
 IF (SELECT count(*) FROM maintenance_runner_ack_outbox)<>2 THEN RAISE EXCEPTION 'native publications missing durable ACK outbox'; END IF;
 IF EXISTS(SELECT FROM maintenance_runner_ack_outbox WHERE acknowledged_at IS NOT NULL) THEN RAISE EXCEPTION 'runner ACK not yet delivered'; END IF;
END $$;
ROLLBACK;
