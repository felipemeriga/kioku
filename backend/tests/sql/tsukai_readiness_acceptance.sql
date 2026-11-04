-- Run after fixture + shipped runtime migrations + 2200, in a disposable DB.
DO $$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.tsukai_completion_receipts WHERE job_id='old-probe' AND consumer='runtime.readiness') THEN
        RAISE EXCEPTION 'old readiness backfill missing';
    END IF;
    IF has_table_privilege('tsukai_readiness_fixture_runtime','public.tsukai_completion_receipts','SELECT')
       OR has_table_privilege('tsukai_readiness_fixture_runtime','public.tsukai_completion_receipts','INSERT')
       OR has_table_privilege('tsukai_readiness_fixture_runtime','auth.users','SELECT')
       OR has_function_privilege('tsukai_readiness_fixture_runtime','public.tsukai_enqueue_readiness_usage()','EXECUTE') THEN
        RAISE EXCEPTION 'runtime privilege widened';
    END IF;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='tsukai_readiness_fixture_runtime' AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole)) THEN
        RAISE EXCEPTION 'elevated fixture runtime';
    END IF;
END $$;
SELECT public.readiness_fixture_job('fresh-probe','11111111-1111-1111-1111-111111111111');
SELECT public.readiness_fixture_job('other-operation','11111111-1111-1111-1111-111111111111','contextual');
SELECT public.readiness_fixture_job('mismatched-owner','11111111-1111-1111-1111-111111111111','readiness','22222222-2222-2222-2222-222222222222');
SELECT public.readiness_fixture_job('missing-owner','33333333-3333-3333-3333-333333333333');
SELECT public.readiness_fixture_job('retry-probe','11111111-1111-1111-1111-111111111111');
SELECT public.readiness_fixture_job('scoped-probe','11111111-1111-1111-1111-111111111111');
UPDATE public.tsukai_jobs SET request=(request::jsonb || '{"folder_ids":["folder"]}'::jsonb)::json WHERE id='scoped-probe';
-- Receipt insertion must roll back together with the runner terminal mutation.
BEGIN;
SET LOCAL ROLE tsukai_readiness_fixture_runtime;
UPDATE public.tsukai_attempts SET status='completed',finished_at=1 WHERE id='fresh-probe';
ROLLBACK;
DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM public.tsukai_completion_receipts WHERE job_id='fresh-probe') THEN
        RAISE EXCEPTION 'receipt escaped attempt rollback';
    END IF;
END $$;
-- Only execution writes are available to the actual restricted runtime role.
SET ROLE tsukai_readiness_fixture_runtime;
UPDATE public.tsukai_attempts SET status='completed',finished_at=1,usage='{"complete":true,"output_tokens":3}'
WHERE id IN ('fresh-probe','other-operation','mismatched-owner','missing-owner','scoped-probe');
UPDATE public.tsukai_jobs SET status='completed' WHERE id='fresh-probe';
-- First failed attempt must not permanently disable an eventual success ACK.
UPDATE public.tsukai_attempts SET status='failed',finished_at=1,usage='{"complete":true,"output_tokens":2}' WHERE id='retry-probe';
UPDATE public.tsukai_jobs SET status='queued' WHERE id='retry-probe';
RESET ROLE;
DO $$ BEGIN
    IF (SELECT count(*) FROM public.tsukai_completion_receipts WHERE job_id='fresh-probe') <> 1 THEN RAISE EXCEPTION 'fresh probe not captured'; END IF;
    IF EXISTS(SELECT 1 FROM public.tsukai_completion_receipts WHERE job_id IN ('other-operation','mismatched-owner','missing-owner','scoped-probe')) THEN RAISE EXCEPTION 'unrelated or widened readiness captured'; END IF;
    IF EXISTS(SELECT 1 FROM public.tsukai_completion_receipts WHERE owner_id='22222222-2222-2222-2222-222222222222') THEN RAISE EXCEPTION 'request chose foreign receipt owner'; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.tsukai_completion_receipts WHERE job_id='retry-probe' AND NOT processed AND payload->>'acknowledge_completed'='true') THEN RAISE EXCEPTION 'retry receipt lost pending success policy'; END IF;
END $$;
SET ROLE tsukai_readiness_fixture_runtime;
INSERT INTO public.tsukai_attempts(id,job_id,number,fence,worker_id,status,lease_until,deadline,started_at,native_session_id,resume,counter_segment)
VALUES('retry-attempt-2','retry-probe',2,'fence','fixture','running',9999999999,9999999999,1,'native2',false,'segment2');
BEGIN;
UPDATE public.tsukai_attempts SET status='completed',finished_at=2,usage='{"complete":true,"output_tokens":5}' WHERE id='retry-attempt-2';
UPDATE public.tsukai_jobs SET status='completed' WHERE id='retry-probe';
COMMIT;
-- Duplicate notifications must never enqueue another receipt or reset it.
UPDATE public.tsukai_attempts SET status='completed',finished_at=2 WHERE id IN ('fresh-probe','retry-attempt-2');
RESET ROLE;
DO $$ BEGIN
    IF (SELECT count(*) FROM public.tsukai_completion_receipts WHERE job_id='retry-probe') <> 1 THEN RAISE EXCEPTION 'duplicate retry receipt'; END IF;
    IF (SELECT sum((usage->>'output_tokens')::int) FROM public.tsukai_attempts WHERE job_id='retry-probe') <> 7 THEN RAISE EXCEPTION 'retry attempt usage missing'; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.tsukai_jobs WHERE id='retry-probe' AND status='completed') THEN RAISE EXCEPTION 'retry final job not committed'; END IF;
    IF EXISTS(SELECT 1 FROM public.tsukai_completion_receipts WHERE payload ? 'prompt' OR payload ? 'result') THEN RAISE EXCEPTION 'raw execution evidence copied'; END IF;
END $$;
SELECT 'readiness receipt integration PASS' AS result;
