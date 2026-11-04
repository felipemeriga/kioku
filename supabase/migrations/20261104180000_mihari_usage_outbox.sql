-- Durable copy queue for every terminal native maintenance job, including errors.
CREATE TABLE public.maintenance_usage_outbox (
    job_id text PRIMARY KEY,
    preparation_id uuid NOT NULL REFERENCES public.maintenance_preparations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    outcome text NOT NULL CHECK(outcome IN ('completed','failed','cancelled','uncertain')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    captured_at timestamptz
);
ALTER TABLE public.maintenance_usage_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.maintenance_usage_outbox FROM anon,authenticated;
GRANT ALL ON public.maintenance_usage_outbox TO service_role;
-- Upgrade already-published jobs; per-attempt ledger upserts are idempotent.
INSERT INTO public.maintenance_usage_outbox(job_id,preparation_id,user_id,folder_id,outcome)
SELECT execution_job_id,id,user_id,folder_id,'completed'
FROM public.maintenance_preparations WHERE execution_job_id IS NOT NULL AND request <> '{}'::jsonb;
