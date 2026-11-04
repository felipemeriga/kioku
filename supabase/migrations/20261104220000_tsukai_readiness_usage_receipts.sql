-- Project operational probe usage into the existing durable consumer outbox.
-- Runner privileges stay confined to execution tables; no prompt/result is copied.
CREATE OR REPLACE FUNCTION public.tsukai_enqueue_readiness_usage()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
    IF NEW.finished_at IS NULL OR NEW.status NOT IN ('completed','failed','cancelled','uncertain') THEN
        RETURN NEW;
    END IF;
    INSERT INTO public.tsukai_completion_receipts
        (job_id,owner_id,scope,operation,profile,consumer,reference,payload)
    SELECT j.id,u.id,
        jsonb_build_object('owner_id',u.id::text,'folder_ids','[]'::jsonb,'caller','backend'),
        'readiness','completion','runtime.readiness','runtime.readiness:' || j.id,
        jsonb_build_object('model',j.request->>'model','acknowledge_completed',true)
    FROM public.tsukai_jobs j JOIN auth.users u ON u.id::text=j.owner_id
    WHERE j.id=NEW.job_id AND j.caller='backend' AND j.profile='completion'
        AND j.conversation_id IS NULL AND j.request->>'operation'='readiness'
        AND j.request->>'caller'='backend' AND j.request->>'owner_id'=j.owner_id
        AND j.request->>'profile'='completion'
        AND j.request::jsonb->'folder_ids'='[]'::jsonb
        AND j.request::jsonb->'tool_allowlist'='[]'::jsonb
    ON CONFLICT(job_id) DO NOTHING;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.tsukai_enqueue_readiness_usage() FROM PUBLIC,anon,authenticated,service_role;
CREATE TRIGGER tsukai_readiness_usage_receipt
AFTER INSERT OR UPDATE OF status,finished_at ON public.tsukai_attempts
FOR EACH ROW EXECUTE FUNCTION public.tsukai_enqueue_readiness_usage();

-- One-time backfill includes unsuccessful attempts and jobs awaiting a retry.
-- Receipts wait for terminal job status, then copy every final attempt counter.
INSERT INTO public.tsukai_completion_receipts
    (job_id,owner_id,scope,operation,profile,consumer,reference,payload)
SELECT j.id,u.id,
    jsonb_build_object('owner_id',u.id::text,'folder_ids','[]'::jsonb,'caller','backend'),
    'readiness','completion','runtime.readiness','runtime.readiness:' || j.id,
    jsonb_build_object('model',j.request->>'model','acknowledge_completed',true)
FROM public.tsukai_jobs j JOIN auth.users u ON u.id::text=j.owner_id
WHERE j.caller='backend' AND j.profile='completion' AND j.conversation_id IS NULL
    AND j.request->>'operation'='readiness' AND j.request->>'caller'='backend'
    AND j.request->>'owner_id'=j.owner_id AND j.request->>'profile'='completion'
    AND j.request::jsonb->'folder_ids'='[]'::jsonb
    AND j.request::jsonb->'tool_allowlist'='[]'::jsonb
    AND EXISTS(SELECT 1 FROM public.tsukai_attempts a WHERE a.job_id=j.id
        AND a.finished_at IS NOT NULL AND a.status IN ('completed','failed','cancelled','uncertain'))
ON CONFLICT(job_id) DO NOTHING;
