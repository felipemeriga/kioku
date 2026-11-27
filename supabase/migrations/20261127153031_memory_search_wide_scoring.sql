-- Estimate full-text selectivity from the known query and trim boolean scoring vectors.
CREATE OR REPLACE FUNCTION public.search_agent_memory_v2(
 p_user_id uuid,p_folder_ids uuid[],p_terms text[],
 p_after timestamptz DEFAULT NULL,p_before timestamptz DEFAULT NULL,
 p_session text DEFAULT NULL,p_order text DEFAULT 'chronological',
 p_limit integer DEFAULT 50,p_offset integer DEFAULT 0,
 p_identifiers text[] DEFAULT '{}',p_timezone text DEFAULT 'UTC'
)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public
SET statement_timeout='5s'
SET plan_cache_mode='force_custom_plan' AS $$
DECLARE result jsonb; recall_query tsquery; wide_search boolean := false; stripped_scoring boolean := false;
BEGIN
-- Explicit identifiers often match few chunks. Preserve the previous plan
-- for other searches, including a single ordinary word with high fanout.
IF cardinality(p_terms)=1 THEN
 SELECT ('('||plainto_tsquery('simple',t)::text||
    CASE WHEN plainto_tsquery('english',t)::text<>''
    THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')')::tsquery
 INTO recall_query FROM unnest(p_terms) t
 WHERE t=ANY(p_identifiers) AND (length(t)>=5 OR t~'[_0-9]');
ELSIF cardinality(p_terms)>1
 AND EXISTS(SELECT 1 FROM unnest(p_terms) t WHERE length(t)>0) THEN
 -- Large archives benefit from indexed text filtering and reusing wide vectors.
 -- Session counts avoid scanning chunks merely to choose an execution path.
 SELECT coalesce(sum(s.event_count),0)>=32768 INTO wide_search
 FROM public.agent_evidence_sessions s
 WHERE s.user_id=p_user_id AND s.folder_id=ANY(p_folder_ids) AND s.deleted_at IS NULL
 AND (p_after IS NULL OR s.last_event_at IS NULL OR s.last_event_at>=p_after)
 AND (p_before IS NULL OR s.first_event_at IS NULL OR s.first_event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session);
 IF wide_search THEN
  -- Require thousands of vectors that may benefit from one detoast per chunk.
  -- 4,096 vectors of 2 KiB represent 8 MiB before any repeated term scoring.
  SELECT EXISTS (
   SELECT 1 FROM public.agent_memory_chunks c
   JOIN public.agent_evidence_sessions s
    ON s.id=c.session_id AND s.user_id=c.user_id AND s.folder_id=c.folder_id
   WHERE c.user_id=p_user_id AND c.folder_id=ANY(p_folder_ids) AND s.deleted_at IS NULL
   AND (p_after IS NULL OR s.last_event_at IS NULL OR s.last_event_at>=p_after)
   AND (p_before IS NULL OR s.first_event_at IS NULL OR s.first_event_at<p_before)
   AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
   AND (pg_catalog.pg_column_size(c.lexemes)>=2048
        OR pg_catalog.pg_column_compression(c.lexemes) IS NOT NULL)
   LIMIT 1 OFFSET 4095
  ) INTO wide_search;
 END IF;
END IF;
-- The previous plan is faster on narrow windows with a lower time bound.
IF wide_search AND p_after IS NULL THEN
 stripped_scoring := true;
 -- A custom plan can estimate selectivity from this value before joining candidates.
 WITH terms AS MATERIALIZED (
 SELECT DISTINCT lower(t) term,
  ('('||plainto_tsquery('simple',t)::text||
    CASE WHEN plainto_tsquery('english',t)::text<>''
    THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')')::tsquery q
 FROM unnest(p_terms) t WHERE length(t)>0
)
 SELECT CASE WHEN count(*)>0 THEN string_agg('('||q::text||')',' | ')::tsquery END
 INTO recall_query FROM terms;
END IF;
WITH terms AS MATERIALIZED (
 SELECT DISTINCT lower(t) term,
  ('('||plainto_tsquery('simple',t)::text||
    CASE WHEN plainto_tsquery('english',t)::text<>''
    THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')')::tsquery q
 FROM unnest(p_terms) t WHERE length(t)>0
), query AS NOT MATERIALIZED (
 SELECT CASE WHEN count(*)>0 THEN string_agg('('||q::text||')',' | ')::tsquery END q
 FROM terms
), matched AS MATERIALIZED (
 SELECT c.session_id,c.event_id,c.object_id,c.char_start,c.char_length,c.folder_id,
 e.event_at,e.role,e.event_type,e.record_sequence,e.call_id,e.source_truncated,
 s.native_session_id,s.agent,s.manifest_revision,s.indexed_revision,
 scores.matched_terms,
 scores.term_count + scores.identifier_boost
 + CASE WHEN query.q IS NULL THEN 0 ELSE ts_rank_cd(c.lexemes,query.q,32) END relevance
 FROM public.agent_memory_chunks c
 JOIN public.agent_evidence_events e USING(session_id,event_id)
 JOIN public.agent_evidence_sessions s ON s.id=c.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=c.session_id AND o.object_id=c.object_id
 CROSS JOIN query
 CROSS JOIN LATERAL (
  WITH document AS MATERIALIZED (
   -- Only boolean plainto_tsquery matching uses stripped vectors. Ranking uses c.lexemes.
   SELECT CASE WHEN stripped_scoring THEN pg_catalog.strip(c.lexemes)
               ELSE c.lexemes || ''::tsvector END AS lexemes
  )
  SELECT coalesce(array_agg(t.term), '{}'::text[]) matched_terms,
   count(*) term_count,
   coalesce(sum(CASE WHEN t.term=ANY(p_identifiers) THEN
    CASE WHEN length(t.term)>=5 OR t.term~'[_0-9]' THEN 100 ELSE 0.25 END
    ELSE 0 END),0) identifier_boost
  FROM (
   SELECT term FROM terms WHERE NOT stripped_scoring
   AND CASE WHEN wide_search THEN (SELECT lexemes FROM document)@@q ELSE c.lexemes@@q END
   UNION ALL
   SELECT t.term FROM document d
   CROSS JOIN LATERAL (SELECT term FROM terms WHERE d.lexemes@@q OFFSET 0) t
   WHERE stripped_scoring
  ) t
 ) scores
 WHERE c.user_id=p_user_id AND c.folder_id=ANY(p_folder_ids)
 AND e.user_id=p_user_id AND s.user_id=p_user_id AND s.deleted_at IS NULL
 AND e.displayable AND NOT e.inherited AND o.memory_index_version>=1
 AND o.committed_revision IS NOT NULL
 AND CASE WHEN recall_query IS NOT NULL THEN c.lexemes@@recall_query
     WHEN wide_search THEN c.lexemes@@(SELECT q FROM query)
     ELSE query.q IS NULL OR c.lexemes@@query.q END
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
  AND o.kind='segment' AND o.committed_revision IS NOT NULL AND o.memory_index_version<2)
)
INTO result;
RETURN result;
END
$$;
REVOKE ALL ON FUNCTION public.search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text) TO service_role;
