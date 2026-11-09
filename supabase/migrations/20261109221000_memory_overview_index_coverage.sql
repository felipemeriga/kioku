-- Do not call an original activity inventory complete while captured segments await parsing.
BEGIN;
CREATE OR REPLACE FUNCTION public.agent_memory_overview(
 p_user_id uuid,p_folder_ids uuid[],p_after timestamptz DEFAULT NULL,
 p_before timestamptz DEFAULT NULL,p_session text DEFAULT NULL,p_timezone text DEFAULT 'UTC'
) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=public,pg_temp SET statement_timeout='5s' AS $$
WITH folders AS MATERIALIZED (
 SELECT id FROM public.folders WHERE user_id=p_user_id AND id=ANY(p_folder_ids)
), journals AS MATERIALIZED (
 SELECT j.folder_id,j.session_id,j.agent,j.title,j.body,j.captured_at,j.entry_id
 FROM public.agent_journal_search_entries j JOIN folders f ON f.id=j.folder_id
 WHERE j.user_id=p_user_id AND (p_after IS NULL OR j.captured_at>=p_after)
 AND (p_before IS NULL OR j.captured_at<p_before)
 AND (p_session IS NULL OR starts_with(j.session_id,p_session))
), originals AS MATERIALIZED (
 SELECT e.folder_id,s.id AS session_id,s.native_session_id,s.agent,
 (e.event_at AT TIME ZONE p_timezone)::date AS date,count(*) AS event_count
 FROM public.agent_evidence_events e
 JOIN folders f ON f.id=e.folder_id
 JOIN public.agent_evidence_sessions s ON s.id=e.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=e.session_id AND o.object_id=e.object_id
 WHERE e.user_id=p_user_id AND s.user_id=p_user_id AND s.folder_id=e.folder_id
 AND s.deleted_at IS NULL AND e.displayable AND NOT e.inherited
 AND o.committed_revision IS NOT NULL
 AND (p_after IS NULL OR e.event_at>=p_after) AND (p_before IS NULL OR e.event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
 GROUP BY e.folder_id,s.id,s.native_session_id,s.agent,(e.event_at AT TIME ZONE p_timezone)::date
)
SELECT jsonb_build_object(
 'snapshot_at',statement_timestamp(),
 'index_pending_objects',(
  SELECT count(*) FROM public.agent_evidence_objects o
  JOIN public.agent_evidence_sessions s ON s.id=o.session_id
  JOIN folders f ON f.id=s.folder_id
  WHERE s.user_id=p_user_id AND s.deleted_at IS NULL AND o.kind='segment'
  AND o.committed_revision IS NOT NULL AND o.indexed_parser_version<1
  AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
 ),
 'entry_count',(SELECT count(*) FROM journals),
 'original_day_count',(SELECT count(*) FROM originals),
 'entries',coalesce((SELECT jsonb_agg(to_jsonb(j) ORDER BY captured_at,entry_id)
 FROM (SELECT * FROM journals ORDER BY captured_at,entry_id LIMIT 2000) j),'[]'),
 'original_days',coalesce((SELECT jsonb_agg(to_jsonb(o) ORDER BY date,folder_id,session_id)
 FROM (SELECT * FROM originals ORDER BY date,folder_id,session_id LIMIT 2000) o),'[]')
)
$$;
REVOKE ALL ON FUNCTION public.agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text) TO service_role;
COMMIT;
