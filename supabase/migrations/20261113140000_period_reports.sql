BEGIN;
CREATE TABLE public.repo_period_reports (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
 kind text NOT NULL CHECK(kind IN ('weekly','monthly')),
 period_start date NOT NULL, period_end date NOT NULL CHECK(period_end>=period_start),
 timezone text NOT NULL, cutoff timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('draft','final')),
 revision integer NOT NULL CHECK(revision>0), source_digest text NOT NULL,
 content jsonb NOT NULL, sources jsonb NOT NULL, coverage jsonb NOT NULL,
 generated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(user_id,folder_id,kind,timezone,period_start)
);
CREATE TABLE public.repo_period_report_revisions (
 report_id uuid NOT NULL REFERENCES public.repo_period_reports(id) ON DELETE CASCADE,
 revision integer NOT NULL, user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 content jsonb NOT NULL, sources jsonb NOT NULL, coverage jsonb NOT NULL,
 source_digest text NOT NULL, cutoff timestamptz NOT NULL, status text NOT NULL,
 generated_at timestamptz NOT NULL, PRIMARY KEY(report_id,revision)
);
CREATE INDEX repo_reports_scope ON public.repo_period_reports(user_id,folder_id,period_start DESC);
ALTER TABLE public.repo_period_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.repo_period_report_revisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Read own period reports" ON public.repo_period_reports FOR SELECT USING(auth.uid()=user_id);
CREATE POLICY "Read own report revisions" ON public.repo_period_report_revisions FOR SELECT USING(auth.uid()=user_id);
REVOKE ALL ON public.repo_period_reports, public.repo_period_report_revisions FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.repo_period_reports,public.repo_period_report_revisions TO authenticated;
GRANT ALL ON public.repo_period_reports,public.repo_period_report_revisions TO service_role;
ALTER TABLE public.watched_repos ADD COLUMN report_timezone text NOT NULL DEFAULT 'UTC';

CREATE FUNCTION public.period_report_sources(p_user uuid,p_folder uuid,p_after timestamptz,p_before timestamptz,p_timezone text DEFAULT 'UTC')
RETURNS jsonb LANGUAGE sql STABLE SET search_path=public AS $$
WITH journals AS (
 SELECT e.*,
 row_number() OVER(PARTITION BY (captured_at AT TIME ZONE p_timezone)::date,session_id ORDER BY captured_at DESC,entry_id) AS n
 FROM agent_journal_search_entries e WHERE user_id=p_user AND folder_id=p_folder
 AND captured_at>=p_after AND captured_at<p_before
), events AS (
 SELECT e.*,
 row_number() OVER(PARTITION BY (event_at AT TIME ZONE p_timezone)::date ORDER BY event_at DESC,event_id) AS n
 FROM agent_evidence_events e
 JOIN agent_evidence_sessions s ON s.id=e.session_id AND s.user_id=p_user AND s.deleted_at IS NULL
 JOIN agent_evidence_sessions root ON root.id=s.root_session_id AND root.user_id=p_user AND root.deleted_at IS NULL
 WHERE e.user_id=p_user AND e.folder_id=p_folder AND e.event_at>=p_after AND e.event_at<p_before
 AND e.displayable AND NOT e.inherited AND e.event_type='tool_result'
)
SELECT jsonb_build_object(
 'entry_count',(SELECT count(*) FROM journals),
 'event_count',(SELECT count(*) FROM events),
 'entries',coalesce((SELECT jsonb_agg(to_jsonb(j)-'n' ORDER BY captured_at,entry_id)
  FROM (SELECT * FROM journals WHERE n<=8 ORDER BY n,captured_at,entry_id LIMIT 240) j),'[]'::jsonb),
 'events',coalesce((SELECT jsonb_agg(to_jsonb(e)-'n' ORDER BY event_at,event_id)
  FROM (SELECT * FROM events WHERE n<=2 ORDER BY n,event_at,event_id LIMIT 16) e),'[]'::jsonb))
$$;
REVOKE ALL ON FUNCTION public.period_report_sources(uuid,uuid,timestamptz,timestamptz,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.period_report_sources(uuid,uuid,timestamptz,timestamptz,text) TO service_role;

CREATE FUNCTION public.apply_period_report_result(p_preparation uuid,p_user uuid,p_job text,p_value jsonb)
RETURNS jsonb LANGUAGE plpgsql SET search_path=public AS $$
DECLARE prep record; old public.repo_period_reports; meta jsonb; src jsonb; result jsonb; written public.repo_period_reports;
BEGIN
 SELECT * INTO prep FROM maintenance_preparations WHERE id=p_preparation AND user_id=p_user AND operation='reports' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'unknown report preparation'; END IF;
 IF prep.execution_job_id IS NOT NULL THEN
  IF prep.execution_job_id<>p_job THEN RAISE EXCEPTION 'execution already bound'; END IF;
  RETURN prep.publication;
 END IF;
 PERFORM 1 FROM folders WHERE id=prep.folder_id AND user_id=p_user AND kind='repo' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'repository owner mismatch'; END IF;
 meta:=prep.snapshot->'report';
 SELECT * INTO old FROM repo_period_reports WHERE user_id=p_user AND folder_id=prep.folder_id
 AND kind=meta->>'kind' AND timezone=meta->>'timezone' AND period_start=(meta->>'period_start')::date;
 IF coalesce(old.revision,0)<>(meta->>'expected_revision')::integer THEN RAISE EXCEPTION 'stale report revision'; END IF;
 IF coalesce((SELECT report_timezone FROM watched_repos WHERE user_id=p_user AND folder_id=prep.folder_id LIMIT 1),'UTC')<>meta->>'timezone' THEN
  RAISE EXCEPTION 'report timezone changed';
 END IF;
 SELECT coalesce(jsonb_agg(s),'[]'::jsonb) INTO src FROM jsonb_array_elements(prep.snapshot->'input'->'sources') s
 WHERE s->>'id' IN (
  SELECT jsonb_array_elements_text(p_value->'summary_source_ids')
  UNION SELECT jsonb_array_elements_text(i->'source_ids') FROM jsonb_array_elements(p_value->'sections') sec, jsonb_array_elements(sec->'items') i
 );
 INSERT INTO repo_period_reports(user_id,folder_id,kind,period_start,period_end,timezone,cutoff,status,revision,source_digest,content,sources,coverage)
 VALUES(p_user,prep.folder_id,meta->>'kind',(meta->>'period_start')::date,(meta->>'period_end')::date,meta->>'timezone',
 (meta->>'cutoff')::timestamptz,meta->>'status',coalesce(old.revision,0)+1,meta->>'source_digest',p_value,src,meta->'coverage')
 ON CONFLICT(user_id,folder_id,kind,timezone,period_start) DO UPDATE SET cutoff=excluded.cutoff,status=excluded.status,
 revision=excluded.revision,source_digest=excluded.source_digest,content=excluded.content,sources=excluded.sources,coverage=excluded.coverage,generated_at=clock_timestamp()
 RETURNING * INTO written;
 INSERT INTO repo_period_report_revisions(report_id,revision,user_id,content,sources,coverage,source_digest,cutoff,status,generated_at)
 VALUES(written.id,written.revision,p_user,written.content,written.sources,written.coverage,written.source_digest,written.cutoff,written.status,written.generated_at);
 result:=jsonb_build_object('ok',true,'updated',true,'report_id',written.id,'revision',written.revision,'kind',written.kind);
 IF prep.request<>'{}'::jsonb THEN
  INSERT INTO maintenance_runner_ack_outbox(preparation_id,user_id,folder_id,job_id) VALUES(prep.id,p_user,prep.folder_id,p_job) ON CONFLICT(preparation_id) DO NOTHING;
 END IF;
 UPDATE maintenance_preparations SET execution_job_id=p_job,publication=result WHERE id=prep.id;
 RETURN result;
END;
$$;
REVOKE ALL ON FUNCTION public.apply_period_report_result(uuid,uuid,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.apply_period_report_result(uuid,uuid,text,jsonb) TO service_role;

ALTER TABLE public.maintenance_preparations DROP CONSTRAINT maintenance_preparations_operation_check;
ALTER TABLE public.maintenance_preparations ADD CONSTRAINT maintenance_preparations_operation_check CHECK(operation IN ('review_plan','activity','how_it_runs','deployment','reground','documentation','learnings','reports'));
COMMIT;
