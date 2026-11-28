-- Journals choose an original session within the same read snapshot.
CREATE FUNCTION public.search_agent_memory_journal_guided(
 p_user_id uuid,p_folder_ids uuid[],p_terms text[],
 p_after timestamptz,p_before timestamptz,p_session uuid,p_order text,
 p_limit integer,p_offset integer,p_identifiers text[],p_timezone text
)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=public SET statement_timeout='5s' AS $$
DECLARE
 selected_session uuid;
 selected_folder uuid;
BEGIN
 IF p_before IS NULL OR (p_offset>0 AND p_session IS NULL) THEN
  RAISE EXCEPTION 'evidence_not_found';
 END IF;
 IF p_session IS NULL THEN
  WITH terms AS MATERIALIZED (
   SELECT DISTINCT lower(t) AS term,plainto_tsquery('simple',t) || plainto_tsquery('english',t) AS query
   FROM unnest(p_terms) t WHERE length(t)>0
  ), eligible AS MATERIALIZED (
   SELECT s.id,s.folder_id,j.entry_id,j.captured_at,j.title,j.summary,j.body
   FROM public.agent_journal_search_entries j
   JOIN public.agent_journal_days d USING(user_id,folder_id,journal_date)
   JOIN public.agent_evidence_sessions s ON s.user_id=j.user_id AND s.folder_id=j.folder_id
    AND s.agent=j.agent AND s.native_session_id=j.session_id AND s.deleted_at IS NULL
   WHERE j.user_id=p_user_id AND j.folder_id=ANY(p_folder_ids)
    AND d.search_sha256=d.content_sha256 AND d.synced_at<p_before
    AND j.captured_at<p_before AND (p_after IS NULL OR j.captured_at>=p_after)
  )
  SELECT j.id,j.folder_id INTO selected_session,selected_folder
  FROM eligible j
  CROSS JOIN LATERAL (
   SELECT to_tsvector('simple',j.title)||to_tsvector('english',j.title) AS title,
          to_tsvector('simple',j.summary)||to_tsvector('english',j.summary) AS summary,
          to_tsvector('simple',j.body)||to_tsvector('english',j.body) AS body
   OFFSET 0
  ) v
  CROSS JOIN LATERAL (
   SELECT count(*) FILTER(WHERE v.title@@query) AS title_hits,
          count(*) FILTER(WHERE v.summary@@query) AS summary_hits,
          count(*) FILTER(WHERE v.body@@query) AS body_hits,
          count(*) FILTER(WHERE term=ANY(p_identifiers)
                           AND (v.title@@query OR v.summary@@query OR v.body@@query)) AS identifier_hits
   FROM terms
  ) m
  WHERE m.title_hits+m.summary_hits+m.body_hits>=2 OR m.identifier_hits>0
  ORDER BY 2*m.title_hits+m.summary_hits+m.body_hits+3*m.identifier_hits DESC,
           j.captured_at DESC,j.id,j.entry_id
  LIMIT 1;
 ELSE
  SELECT s.id,s.folder_id INTO selected_session,selected_folder
  FROM public.agent_evidence_sessions s
  WHERE s.id=p_session AND s.user_id=p_user_id AND s.folder_id=ANY(p_folder_ids)
   AND s.deleted_at IS NULL;
 END IF;

 -- The existing search accepts native session prefixes as well as UUIDs.
 -- A colliding prefix must never silently widen this session-local page.
 IF selected_session IS NULL OR EXISTS (
  SELECT 1 FROM public.agent_evidence_sessions s
  WHERE s.user_id=p_user_id AND s.folder_id=selected_folder AND s.deleted_at IS NULL
   AND s.id<>selected_session AND starts_with(s.native_session_id,selected_session::text)
 ) THEN
  IF p_session IS NOT NULL THEN
   RAISE EXCEPTION 'evidence_not_found';
  END IF;
  RETURN NULL;
 END IF;

 RETURN jsonb_build_object(
  'session_id',selected_session,
  'folder_id',selected_folder,
  'result',public.search_agent_memory_v2(
   p_user_id,ARRAY[selected_folder],p_terms,p_after,p_before,selected_session::text,
   p_order,p_limit,p_offset,p_identifiers,p_timezone
  )
 );
END
$$;
REVOKE ALL ON FUNCTION public.search_agent_memory_journal_guided(
 uuid,uuid[],text[],timestamptz,timestamptz,uuid,text,integer,integer,text[],text
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.search_agent_memory_journal_guided(
 uuid,uuid[],text[],timestamptz,timestamptz,uuid,text,integer,integer,text[],text
) TO service_role;
