-- A selected but never-created guide must not deadlock an otherwise valid pass.
BEGIN;
SET LOCAL ROLE service_role;
INSERT INTO auth.users VALUES ('10000000-0000-0000-0000-000000000001');
INSERT INTO folders VALUES ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','repo');
INSERT INTO maintenance_preparations(id,user_id,folder_id,operation,head_sha,input_digest,idempotency_key,snapshot,request)
VALUES('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','review_plan',repeat('a',40),'d','existing-plan','{}','{}');
INSERT INTO maintenance_review_passes(folder_id,user_id,preparation_id,head_sha,selected,reviewed,acknowledged,created_at)
VALUES('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',repeat('a',40),'["activity","documentation"]','["activity","architecture","documentation"]','[]',clock_timestamp());
DO $$ BEGIN
 IF acknowledge_absent_mihari_documentation('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000099',repeat('a',40)) THEN RAISE EXCEPTION 'foreign owner accepted'; END IF;
 IF acknowledge_absent_mihari_documentation('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',repeat('b',40)) THEN RAISE EXCEPTION 'foreign HEAD accepted'; END IF;
 IF NOT acknowledge_absent_mihari_documentation('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',repeat('a',40)) THEN RAISE EXCEPTION 'confirmed absence not acknowledged'; END IF;
 IF (SELECT acknowledged @> selected FROM maintenance_review_passes) THEN RAISE EXCEPTION 'other outstanding operation falsely acknowledged'; END IF;
 IF (SELECT section_reviews ? 'architecture' FROM repo_freshness) THEN RAISE EXCEPTION 'whole briefing falsely marked reviewed'; END IF;
END $$;
-- The real model-backed activity publication was already acknowledged at this HEAD.
UPDATE maintenance_review_passes SET acknowledged=acknowledged || '["activity"]';
SELECT acknowledge_absent_mihari_documentation('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',repeat('a',40));
DO $$ BEGIN
 IF NOT (SELECT acknowledged @> selected FROM maintenance_review_passes) THEN RAISE EXCEPTION 'existing pass still deadlocked'; END IF;
 IF (SELECT section_reviews->'architecture'->>'head_sha' FROM repo_freshness) IS DISTINCT FROM repeat('a',40) THEN RAISE EXCEPTION 'completed pass not reviewed'; END IF;
 IF (SELECT section_reviews->'documentation'->>'reason' FROM repo_freshness) IS DISTINCT FROM 'absent' THEN RAISE EXCEPTION 'missing absence provenance'; END IF;
 IF (SELECT section_reviews->'documentation'->>'document_exists' FROM repo_freshness) IS DISTINCT FROM 'false' THEN RAISE EXCEPTION 'review falsely claims guide exists'; END IF;
 IF EXISTS(SELECT FROM repo_documentation) OR EXISTS(SELECT FROM folder_summaries) THEN RAISE EXCEPTION 'absence acknowledgement regenerated facts'; END IF;
END $$;
-- Existing documents require normal model validation/publication, never this shortcut.
INSERT INTO repo_documentation(user_id,folder_id,content,abstract) VALUES('10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','Existing guide','Existing');
UPDATE maintenance_review_passes SET acknowledged=acknowledged - 'documentation';
DO $$ BEGIN
 IF acknowledge_absent_mihari_documentation('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',repeat('a',40)) THEN RAISE EXCEPTION 'existing document bypassed validation'; END IF;
 IF (SELECT acknowledged ? 'documentation' FROM maintenance_review_passes) THEN RAISE EXCEPTION 'existing document incorrectly acknowledged'; END IF;
END $$;
ROLLBACK;
