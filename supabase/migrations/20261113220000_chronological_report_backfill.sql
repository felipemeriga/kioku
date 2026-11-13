BEGIN;

CREATE INDEX IF NOT EXISTS agent_evidence_report_activity
ON public.agent_evidence_events(user_id,folder_id,event_at)
WHERE displayable AND NOT inherited;

-- Discover actual activity periods, including journals/originals from any year.
-- These are metadata reads; raw transcript objects are never scanned here.
CREATE FUNCTION public.period_report_activity(p_user uuid,p_folder uuid,p_timezone text DEFAULT 'UTC')
RETURNS jsonb LANGUAGE sql STABLE SET search_path=public AS $$
WITH journal_days AS (
 SELECT (e.captured_at AT TIME ZONE p_timezone)::date AS day,
 count(*)::bigint AS journals,0::bigint AS originals,max(e.captured_at) AS last_at,
 md5(string_agg(DISTINCT d.content_sha256,',' ORDER BY d.content_sha256)) AS signature
 FROM agent_journal_search_entries e
 JOIN agent_journal_days d USING(user_id,folder_id,journal_date)
 WHERE e.user_id=p_user AND e.folder_id=p_folder
 GROUP BY 1
), original_days AS (
 SELECT (e.event_at AT TIME ZONE p_timezone)::date AS day,
 0::bigint AS journals,count(*)::bigint AS originals,max(e.event_at) AS last_at,
 md5(count(*)::text || ':' || max(e.event_at)::text || ':' ||
 coalesce(string_agg(DISTINCT o.sha256,',' ORDER BY o.sha256),'')) AS signature
 FROM agent_evidence_events e
 JOIN agent_evidence_sessions s ON s.id=e.session_id AND s.user_id=p_user AND s.deleted_at IS NULL
 JOIN agent_evidence_sessions root ON root.id=s.root_session_id AND root.user_id=p_user AND root.deleted_at IS NULL
 JOIN agent_evidence_objects o ON o.session_id=e.session_id AND o.object_id=e.object_id
 WHERE e.user_id=p_user AND e.folder_id=p_folder AND e.displayable AND NOT e.inherited AND e.event_at IS NOT NULL
 GROUP BY 1
), days AS (
 SELECT * FROM journal_days UNION ALL SELECT * FROM original_days
), periods AS (
 SELECT bucket.kind,bucket.start AS period_start,sum(journals) AS journal_entries,
 sum(originals) AS original_events,max(last_at) AS last_activity_at,
 md5(string_agg(day::text || ':' || signature,',' ORDER BY day,signature)) AS activity_signature
 FROM days CROSS JOIN LATERAL (VALUES
 ('weekly',date_trunc('week',day::timestamp)::date),
 ('monthly',date_trunc('month',day::timestamp)::date)
 ) bucket(kind,start)
 GROUP BY bucket.kind,bucket.start
)
SELECT coalesce(jsonb_agg(to_jsonb(periods) ORDER BY period_start DESC,kind),'[]'::jsonb) FROM periods
$$;
REVOKE ALL ON FUNCTION public.period_report_activity(uuid,uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.period_report_activity(uuid,uuid,text) TO service_role;

-- Preserve beginnings and outcomes. A PR's first journal mention brings its
-- preceding two turns so implementation updates do not lose the original goal.
CREATE FUNCTION public.period_report_source_snapshot(
 p_user uuid,p_folder uuid,p_after timestamptz,p_before timestamptz,
 p_timezone text DEFAULT 'UTC',p_terms text[] DEFAULT '{}')
RETURNS jsonb LANGUAGE sql STABLE SET search_path=public AS $$
WITH journals AS MATERIALIZED (
 SELECT e.*,row_number() OVER(
 PARTITION BY (captured_at AT TIME ZONE p_timezone)::date,session_id
 ORDER BY captured_at,entry_id) AS n,
 count(*) OVER(PARTITION BY (captured_at AT TIME ZONE p_timezone)::date,session_id) AS total
 FROM agent_journal_search_entries e WHERE user_id=p_user AND folder_id=p_folder
 AND captured_at>=p_after AND captured_at<p_before
), terms AS (
 SELECT term FROM unnest(p_terms) term WHERE term ~ '^[0-9]{1,10}$' LIMIT 16
), first_mentions AS (
 SELECT anchor.* FROM terms CROSS JOIN LATERAL (
 SELECT j.* FROM journals j WHERE j.body ~ ('#' || term || '([^0-9]|$)')
 ORDER BY captured_at,entry_id LIMIT 1
 ) anchor
), context AS (
 SELECT DISTINCT previous.entry_id FROM first_mentions anchor CROSS JOIN LATERAL (
 SELECT j.entry_id FROM journals j
 WHERE j.session_id=anchor.session_id AND (j.captured_at,j.entry_id)<=(anchor.captured_at,anchor.entry_id)
 ORDER BY j.captured_at DESC,j.entry_id DESC LIMIT 3
 ) previous
), sampled AS (
 SELECT j.*,EXISTS(SELECT 1 FROM context c WHERE c.entry_id=j.entry_id) AS context_anchor
 FROM journals j WHERE EXISTS(SELECT 1 FROM context c WHERE c.entry_id=j.entry_id)
 OR j.n IN (SELECT 1+round(i*(j.total-1)/7.0)::bigint FROM generate_series(0,7) i)
), events AS (
 SELECT e.*,row_number() OVER(PARTITION BY (event_at AT TIME ZONE p_timezone)::date
 ORDER BY CASE WHEN event_type='tool_result' THEN 0
 WHEN event_type='message' AND role='assistant' THEN 1
 WHEN event_type='message' AND role='user' THEN 2 ELSE 3 END,event_at DESC,event_id) AS n
 FROM agent_evidence_events e
 JOIN agent_evidence_sessions s ON s.id=e.session_id AND s.user_id=p_user AND s.deleted_at IS NULL
 JOIN agent_evidence_sessions root ON root.id=s.root_session_id AND root.user_id=p_user AND root.deleted_at IS NULL
 WHERE e.user_id=p_user AND e.folder_id=p_folder AND e.event_at>=p_after AND e.event_at<p_before
 AND e.displayable AND NOT e.inherited
)
SELECT jsonb_build_object(
 'entry_count',(SELECT count(*) FROM journals),'event_count',(SELECT count(*) FROM events),
 'entries',coalesce((SELECT jsonb_agg(to_jsonb(j)-'n'-'total' ORDER BY captured_at,entry_id)
 FROM (SELECT * FROM sampled ORDER BY context_anchor DESC,
 CASE WHEN n=1 OR n=total THEN 0 ELSE 1 END,captured_at,entry_id LIMIT 240) j),'[]'::jsonb),
 'events',coalesce((SELECT jsonb_agg(to_jsonb(e)-'n' ORDER BY event_at,event_id)
 FROM (SELECT * FROM events WHERE n<=2 ORDER BY n,event_at,event_id LIMIT 96) e),'[]'::jsonb))
$$;
REVOKE ALL ON FUNCTION public.period_report_source_snapshot(uuid,uuid,timestamptz,timestamptz,text,text[]) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.period_report_source_snapshot(uuid,uuid,timestamptz,timestamptz,text,text[]) TO service_role;

CREATE OR REPLACE FUNCTION public.apply_period_report_result(p_preparation uuid,p_user uuid,p_job text,p_value jsonb)
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
  UNION SELECT selected #>> '{}' FROM jsonb_path_query(p_value, '$.**.source_ids[*]') selected
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


COMMIT;
