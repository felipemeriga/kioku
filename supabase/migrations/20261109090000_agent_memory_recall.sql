-- Rebuildable lexical projections. Original bodies remain in private Storage.
ALTER TABLE public.agent_evidence_objects ADD COLUMN memory_index_version integer NOT NULL DEFAULT 0;
CREATE TABLE public.agent_memory_chunks (
 session_id uuid NOT NULL, event_id text NOT NULL, object_id text NOT NULL,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
 char_start integer NOT NULL CHECK(char_start>=0), char_length integer NOT NULL CHECK(char_length BETWEEN 1 AND 2000),
 lexemes tsvector NOT NULL,
 PRIMARY KEY(session_id,event_id,char_start),
 FOREIGN KEY(session_id,event_id) REFERENCES public.agent_evidence_events(session_id,event_id) ON DELETE CASCADE
);
CREATE INDEX agent_memory_lexical ON public.agent_memory_chunks USING gin(lexemes);
CREATE INDEX agent_memory_scope ON public.agent_memory_chunks(user_id,folder_id,session_id);
ALTER TABLE public.agent_memory_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_read ON public.agent_memory_chunks FOR SELECT TO authenticated USING(user_id=auth.uid());
GRANT SELECT ON public.agent_memory_chunks TO authenticated;
GRANT ALL ON public.agent_memory_chunks TO service_role;

CREATE FUNCTION public.publish_agent_memory_index(p_session_id uuid,p_object_id text,p_chunks jsonb,p_reset boolean DEFAULT false,p_complete boolean DEFAULT true)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.agent_evidence_sessions%ROWTYPE; c jsonb;
BEGIN
 SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=p_session_id FOR UPDATE;
 IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects WHERE session_id=s.id AND object_id=p_object_id AND committed_revision IS NOT NULL AND indexed_parser_version>=1) THEN RAISE EXCEPTION 'evidence_not_indexed'; END IF;
 IF jsonb_array_length(p_chunks)>500 THEN RAISE EXCEPTION 'memory_batch_too_large'; END IF;
 IF p_reset THEN
  UPDATE public.agent_evidence_objects SET memory_index_version=0 WHERE session_id=s.id AND object_id=p_object_id;
  DELETE FROM public.agent_memory_chunks WHERE session_id=s.id AND object_id=p_object_id;
 END IF;
 FOR c IN SELECT * FROM jsonb_array_elements(p_chunks) LOOP
  IF length(c->>'text')<>(c->>'char_length')::integer THEN RAISE EXCEPTION 'invalid_memory_span'; END IF;
  INSERT INTO public.agent_memory_chunks(session_id,event_id,object_id,user_id,folder_id,char_start,char_length,lexemes)
   SELECT s.id,e.event_id,p_object_id,s.user_id,s.folder_id,(c->>'char_start')::integer,(c->>'char_length')::integer,
     to_tsvector('simple',c->>'text')||to_tsvector('english',c->>'text')
   FROM public.agent_evidence_events e WHERE e.session_id=s.id AND e.object_id=p_object_id AND e.event_id=c->>'event_id' AND e.displayable AND NOT e.inherited
  ON CONFLICT(session_id,event_id,char_start) DO UPDATE SET lexemes=excluded.lexemes,char_length=excluded.char_length;
 END LOOP;
 IF p_complete THEN UPDATE public.agent_evidence_objects SET memory_index_version=1 WHERE session_id=s.id AND object_id=p_object_id; END IF;
END $$;

CREATE FUNCTION public.search_agent_memory(p_user_id uuid,p_folder_ids uuid[],p_terms text[],p_after timestamptz DEFAULT NULL,p_before timestamptz DEFAULT NULL,p_session text DEFAULT NULL,p_order text DEFAULT 'chronological',p_limit integer DEFAULT 50,p_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public SET statement_timeout='5s' AS $$
WITH query AS (
 SELECT CASE WHEN cardinality(p_terms)>0 THEN array_to_string(ARRAY(SELECT '('||plainto_tsquery('simple',t)::text||CASE WHEN plainto_tsquery('english',t)::text<>'' THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')' FROM unnest(p_terms) t WHERE length(t)>0),' | ')::tsquery END q
), matched AS MATERIALIZED (
 SELECT c.session_id,c.event_id,c.object_id,c.char_start,c.char_length,c.folder_id,
 e.event_at,e.role,e.event_type,e.record_sequence,e.call_id,e.source_truncated,
 s.native_session_id,s.agent,s.manifest_revision,s.indexed_revision,
 CASE WHEN query.q IS NULL THEN 0 ELSE ts_rank_cd(c.lexemes,query.q) END relevance,
 row_number() OVER(PARTITION BY c.session_id,c.event_id ORDER BY CASE WHEN query.q IS NULL THEN 0 ELSE ts_rank_cd(c.lexemes,query.q) END DESC,c.char_start) chunk_rank
 FROM public.agent_memory_chunks c
 JOIN public.agent_evidence_events e USING(session_id,event_id)
 JOIN public.agent_evidence_sessions s ON s.id=c.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=c.session_id AND o.object_id=c.object_id CROSS JOIN query
 WHERE c.user_id=p_user_id AND c.folder_id=ANY(p_folder_ids) AND e.user_id=p_user_id AND s.user_id=p_user_id
 AND s.deleted_at IS NULL AND e.displayable AND NOT e.inherited AND o.memory_index_version=1
 AND o.committed_revision IS NOT NULL AND (query.q IS NULL OR c.lexemes@@query.q)
 AND (p_after IS NULL OR e.event_at>=p_after) AND (p_before IS NULL OR e.event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
), events AS MATERIALIZED(SELECT * FROM matched WHERE chunk_rank=1),
ranked AS (SELECT *,row_number() OVER(PARTITION BY folder_id,(event_at AT TIME ZONE 'UTC')::date ORDER BY relevance DESC,event_at DESC NULLS LAST,event_id) temporal_rank FROM events),
page AS (SELECT * FROM ranked ORDER BY
 CASE WHEN p_order='chronological' AND cardinality(p_terms)>0 THEN temporal_rank END ASC,
 CASE WHEN p_order='relevance' OR (p_order='chronological' AND cardinality(p_terms)>0) THEN relevance END DESC,
 CASE WHEN p_order='latest' THEN event_at END DESC NULLS LAST,
 CASE WHEN p_order<>'latest' THEN event_at END ASC NULLS LAST,session_id,record_sequence
 LIMIT greatest(1,least(p_limit,50)) OFFSET greatest(0,least(p_offset,10000)))
SELECT jsonb_build_object('matches',coalesce((SELECT jsonb_agg(to_jsonb(page)||jsonb_build_object('content_preview',e.content_preview)) FROM page JOIN public.agent_evidence_events e USING(session_id,event_id)),'[]'),
 'total_matches',(SELECT count(*) FROM events),
 'has_more',(SELECT count(*) FROM events)>p_offset+p_limit,
 'index_pending_objects',(SELECT count(*) FROM public.agent_evidence_objects o JOIN public.agent_evidence_sessions s ON s.id=o.session_id WHERE o.user_id=p_user_id AND o.folder_id=ANY(p_folder_ids) AND s.deleted_at IS NULL AND o.kind='segment' AND o.committed_revision IS NOT NULL AND o.memory_index_version<1))
$$;
REVOKE ALL ON FUNCTION public.publish_agent_memory_index(uuid,text,jsonb,boolean,boolean) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.search_agent_memory(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.publish_agent_memory_index(uuid,text,jsonb,boolean,boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_agent_memory(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer) TO service_role;
