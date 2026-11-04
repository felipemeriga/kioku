-- Isolated PostgreSQL fixture prerequisites; never apply to an application database.
CREATE SCHEMA auth;
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE TABLE public.conversations(id uuid PRIMARY KEY);
DO $$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='tsukai_readiness_fixture_runtime') THEN
        CREATE ROLE tsukai_readiness_fixture_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
    END IF;
END $$;
INSERT INTO auth.users VALUES ('11111111-1111-1111-1111-111111111111'),('22222222-2222-2222-2222-222222222222');

-- Appended by test setup from shipped 2000 receipt schema:
CREATE TABLE public.tsukai_completion_receipts (
  job_id text PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id uuid REFERENCES public.conversations(id) ON DELETE CASCADE,
  scope jsonb NOT NULL,
  operation text NOT NULL,
  profile text NOT NULL,
  consumer text NOT NULL,
  reference text NOT NULL,
  payload jsonb NOT NULL,
  acknowledged boolean NOT NULL DEFAULT false,
  processed boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_attempt_at timestamptz NOT NULL DEFAULT 'epoch'
);
ALTER TABLE public.tsukai_completion_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_completion_receipts FROM anon,authenticated;
GRANT ALL ON public.tsukai_completion_receipts TO service_role;
CREATE FUNCTION public.readiness_fixture_job(job_id text, owner_id text, operation text DEFAULT 'readiness', request_owner text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$ BEGIN
    INSERT INTO public.tsukai_jobs(id,owner_id,caller,idempotency_key,payload_hash,request_sha256,request,status,profile,attempt_count,next_seq,created_at,updated_at,queue_deadline,cancel_requested)
    VALUES(job_id,owner_id,'backend',job_id,'hash','hash',jsonb_build_object('owner_id',COALESCE(request_owner,owner_id),'operation',operation,'caller','backend','profile','completion','folder_ids','[]'::jsonb,'tool_allowlist','[]'::jsonb,'model','claude-haiku-4-5-20251001'),'running','completion',1,1,0,0,9999999999,false);
    INSERT INTO public.tsukai_attempts(id,job_id,number,fence,worker_id,status,lease_until,deadline,started_at,native_session_id,resume,counter_segment)
    VALUES(job_id,job_id,1,'fence','fixture','running',9999999999,9999999999,0,'native',false,'segment');
END $$;
SELECT public.readiness_fixture_job('old-probe','11111111-1111-1111-1111-111111111111');
UPDATE public.tsukai_attempts SET status='completed',finished_at=1,usage='{"complete":true,"output_tokens":3}' WHERE id='old-probe';
UPDATE public.tsukai_jobs SET status='completed' WHERE id='old-probe';
GRANT USAGE ON SCHEMA public TO tsukai_readiness_fixture_runtime;
GRANT SELECT,INSERT,UPDATE ON public.tsukai_jobs,public.tsukai_attempts TO tsukai_readiness_fixture_runtime;
CREATE POLICY fixture_runner ON public.tsukai_jobs TO tsukai_readiness_fixture_runtime USING(true) WITH CHECK(true);
CREATE POLICY fixture_runner ON public.tsukai_attempts TO tsukai_readiness_fixture_runtime USING(true) WITH CHECK(true);
