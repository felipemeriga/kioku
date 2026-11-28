-- Return bounded journal candidates; these are reports used for orientation.
CREATE FUNCTION public.discover_agent_memory_journals(
 p_user_id uuid,p_folder_ids uuid[],p_terms text[],
 p_after timestamptz,p_before timestamptz,p_identifiers text[]
)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=public SET statement_timeout='5s' AS $$
  WITH terms AS MATERIALIZED (
   SELECT DISTINCT lower(t) AS term,plainto_tsquery('simple',t) || plainto_tsquery('english',t) AS query
   FROM unnest(p_terms) t WHERE length(t)>0
  ), eligible AS MATERIALIZED (
   SELECT s.id,s.native_session_id,s.folder_id,j.entry_id,j.journal_date,j.captured_at,d.synced_at,
          d.revision,j.title,j.summary,j.body
   FROM public.agent_journal_search_entries j
   JOIN public.agent_journal_days d USING(user_id,folder_id,journal_date)
   JOIN public.agent_evidence_sessions s ON s.user_id=j.user_id AND s.folder_id=j.folder_id
    AND s.agent=j.agent AND s.native_session_id=j.session_id AND s.deleted_at IS NULL
   WHERE j.user_id=p_user_id AND j.folder_id=ANY(p_folder_ids)
    AND d.search_sha256=d.content_sha256 AND d.synced_at<p_before
    AND j.captured_at<p_before AND (p_after IS NULL OR j.captured_at>=p_after)
  ), ranked AS (
  SELECT j.id AS session_id,j.native_session_id,j.folder_id,j.entry_id,j.journal_date,j.captured_at,j.synced_at,j.revision,
         left(j.title,300) AS title,
         left(j.title||chr(10)||j.summary||chr(10)||j.body,6000) AS summary_excerpt,
         length(j.title||chr(10)||j.summary||chr(10)||j.body)>6000 AS truncated,
         2*m.title_hits+m.summary_hits+m.body_hits+3*m.identifier_hits AS score
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
  LIMIT 30
  )
  SELECT coalesce(jsonb_agg(to_jsonb(ranked)-'score' ORDER BY score DESC,captured_at DESC,session_id,entry_id),'[]')
  FROM ranked;
$$;
REVOKE ALL ON FUNCTION public.discover_agent_memory_journals(uuid,uuid[],text[],timestamptz,timestamptz,text[])
 FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.discover_agent_memory_journals(uuid,uuid[],text[],timestamptz,timestamptz,text[])
 TO service_role;
