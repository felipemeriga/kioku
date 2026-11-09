-- Keep latest strictly temporal within the explicit-identifier candidate set.
-- Additive RPC: old backends keep their existing search contract during rollout.
CREATE OR REPLACE FUNCTION public.search_agent_memory_v2(
 p_user_id uuid,p_folder_ids uuid[],p_terms text[],
 p_after timestamptz DEFAULT NULL,p_before timestamptz DEFAULT NULL,
 p_session text DEFAULT NULL,p_order text DEFAULT 'chronological',
 p_limit integer DEFAULT 50,p_offset integer DEFAULT 0,
 p_identifiers text[] DEFAULT '{}',p_timezone text DEFAULT 'UTC'
)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public
SET statement_timeout='5s' AS $$
WITH terms AS MATERIALIZED (
 SELECT DISTINCT lower(t) term,
  ('('||plainto_tsquery('simple',t)::text||
    CASE WHEN plainto_tsquery('english',t)::text<>''
    THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')')::tsquery q
 FROM unnest(p_terms) t WHERE length(t)>0
), query AS (
 SELECT CASE WHEN count(*)>0 THEN string_agg('('||q::text||')',' | ')::tsquery END q
 FROM terms
), matched AS MATERIALIZED (
 SELECT c.session_id,c.event_id,c.object_id,c.char_start,c.char_length,c.folder_id,
 e.event_at,e.role,e.event_type,e.record_sequence,e.call_id,e.source_truncated,
 s.native_session_id,s.agent,s.manifest_revision,s.indexed_revision,
 ARRAY(SELECT t.term FROM terms t WHERE c.lexemes@@t.q) matched_terms,
 (SELECT count(*) FROM terms t WHERE c.lexemes@@t.q)
 + (SELECT coalesce(sum(CASE WHEN length(t.term)>=5 OR t.term~'[_0-9]'
     THEN 100 ELSE 0.25 END),0) FROM terms t
     WHERE t.term=ANY(p_identifiers) AND c.lexemes@@t.q)
 + CASE WHEN query.q IS NULL THEN 0 ELSE ts_rank_cd(c.lexemes,query.q,32) END relevance
 FROM public.agent_memory_chunks c
 JOIN public.agent_evidence_events e USING(session_id,event_id)
 JOIN public.agent_evidence_sessions s ON s.id=c.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=c.session_id AND o.object_id=c.object_id
 CROSS JOIN query
 WHERE c.user_id=p_user_id AND c.folder_id=ANY(p_folder_ids)
 AND e.user_id=p_user_id AND s.user_id=p_user_id AND s.deleted_at IS NULL
 AND e.displayable AND NOT e.inherited AND o.memory_index_version=1
 AND o.committed_revision IS NOT NULL AND (query.q IS NULL OR c.lexemes@@query.q)
 AND (p_after IS NULL OR e.event_at>=p_after) AND (p_before IS NULL OR e.event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
), focused AS MATERIALIZED (
 SELECT * FROM matched m WHERE
 NOT EXISTS (SELECT 1 FROM matched x WHERE EXISTS (
  SELECT 1 FROM unnest(x.matched_terms) t
  WHERE t=ANY(p_identifiers) AND (length(t)>=5 OR t~'[_0-9]')))
 OR EXISTS (SELECT 1 FROM unnest(m.matched_terms) t
  WHERE t=ANY(p_identifiers) AND (length(t)>=5 OR t~'[_0-9]'))
), events AS MATERIALIZED (
 SELECT DISTINCT ON(session_id,event_id) * FROM focused
 ORDER BY session_id,event_id,relevance DESC,char_start
), ranked AS (
 SELECT *,row_number() OVER(
  PARTITION BY folder_id,(event_at AT TIME ZONE p_timezone)::date
  ORDER BY relevance DESC,event_at DESC NULLS LAST,event_id) temporal_rank
 FROM events
), page AS (
 SELECT * FROM ranked ORDER BY
 CASE WHEN p_order='chronological' AND cardinality(p_terms)>0 THEN temporal_rank END ASC,
 CASE WHEN p_order='relevance' OR (p_order='chronological' AND cardinality(p_terms)>0) THEN relevance END DESC,
 CASE WHEN p_order='latest' THEN event_at END DESC NULLS LAST,
 CASE WHEN p_order<>'latest' THEN event_at END ASC NULLS LAST,session_id,record_sequence
 LIMIT greatest(1,least(p_limit,50)) OFFSET greatest(0,least(p_offset,10000))
)
SELECT jsonb_build_object(
 'matches',coalesce((SELECT jsonb_agg(to_jsonb(page)||jsonb_build_object('content_preview',e.content_preview))
  FROM page JOIN public.agent_evidence_events e USING(session_id,event_id)),'[]'),
 'total_matches',(SELECT count(*) FROM events),
 'has_more',(SELECT count(*) FROM events)>p_offset+p_limit,
 'unmatched_identifiers',coalesce((SELECT jsonb_agg(i) FROM unnest(p_identifiers) i
  WHERE NOT EXISTS(SELECT 1 FROM events e WHERE i=ANY(e.matched_terms))),'[]'),
 'index_pending_objects',(SELECT count(*) FROM public.agent_evidence_objects o
  JOIN public.agent_evidence_sessions s ON s.id=o.session_id
  WHERE o.user_id=p_user_id AND o.folder_id=ANY(p_folder_ids) AND s.deleted_at IS NULL
  AND o.kind='segment' AND o.committed_revision IS NOT NULL AND o.memory_index_version<1)
)
$$;
REVOKE ALL ON FUNCTION public.search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text) TO service_role;
