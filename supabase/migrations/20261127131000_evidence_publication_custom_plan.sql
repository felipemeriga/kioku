-- Plan deduplication for the current session and avoid rewriting already hidden results.
CREATE OR REPLACE FUNCTION public.publish_agent_evidence_index(
    p_session_id uuid, p_object_id text, p_events jsonb, p_state jsonb, p_parser_version integer,
    p_complete boolean DEFAULT true)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public
SET plan_cache_mode='force_custom_plan' AS $$
DECLARE s public.agent_evidence_sessions%ROWTYPE; e jsonb;
BEGIN
    SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=p_session_id FOR UPDATE;
    IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RETURN; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects WHERE session_id=s.id
      AND object_id=p_object_id AND committed_revision IS NOT NULL) THEN
        RAISE EXCEPTION 'evidence_not_committed';
    END IF;
    FOR e IN SELECT * FROM jsonb_array_elements(p_events) LOOP
      INSERT INTO public.agent_evidence_events(session_id,user_id,folder_id,event_id,object_id,
          stream_id,generation,record_sequence,byte_offset,byte_length,event_at,role,event_type,
          native_id,turn_id,call_id,parent_id,inherited,displayable,content_preview,content_length,source_truncated,parser_version)
      VALUES(s.id,s.user_id,s.folder_id,e->>'event_id',p_object_id,e->>'stream_id',
          (e->>'generation')::integer,(e->>'record_sequence')::bigint,(e->>'byte_offset')::bigint,
          (e->>'byte_length')::bigint,(e->>'event_at')::timestamptz,e->>'role',e->>'event_type',
          e->>'native_id',e->>'turn_id',e->>'call_id',e->>'parent_id',
          COALESCE((e->>'inherited')::boolean,false),COALESCE((e->>'displayable')::boolean,true),
          e->>'content_preview',COALESCE((e->>'content_length')::bigint,0),
          COALESCE((e->>'source_truncated')::boolean,false),p_parser_version)
      ON CONFLICT(session_id,event_id) DO UPDATE SET
          content_preview=excluded.content_preview,role=excluded.role,event_type=excluded.event_type,
          displayable=excluded.displayable,inherited=excluded.inherited,
          source_truncated=excluded.source_truncated,content_length=excluded.content_length,
          parser_version=excluded.parser_version
      WHERE agent_evidence_events.parser_version<=excluded.parser_version;
    END LOOP;
    -- Only established native call identities establish duplicate tool-result representations.
    -- Prefer the richer retained result; all alternatives stay available through raw-records.
    UPDATE public.agent_evidence_events e SET displayable=false
      WHERE e.session_id=s.id AND e.displayable AND e.event_type='tool_result' AND e.call_id IS NOT NULL
      AND EXISTS(SELECT 1 FROM public.agent_evidence_events richer WHERE richer.session_id=e.session_id
        AND richer.stream_id=e.stream_id AND richer.generation=e.generation
        AND richer.event_type=e.event_type AND richer.call_id=e.call_id
        AND richer.turn_id IS NOT DISTINCT FROM e.turn_id AND richer.displayable
        AND (richer.content_length>e.content_length OR (richer.content_length=e.content_length
          AND richer.record_sequence<e.record_sequence)));
    UPDATE public.agent_evidence_sessions SET index_generation=index_generation+1 WHERE id=s.id;
    IF NOT p_complete THEN RETURN; END IF;
    UPDATE public.agent_evidence_objects SET indexed_parser_version=p_parser_version,parser_state=p_state
      WHERE session_id=s.id AND object_id=p_object_id AND indexed_parser_version<=p_parser_version;
    UPDATE public.agent_evidence_sessions SET
      event_count=(SELECT count(*) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      first_event_at=(SELECT min(event_at) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      last_event_at=(SELECT max(event_at) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      parser_version=GREATEST(parser_version,p_parser_version),
      indexed_revision=CASE WHEN NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects
        WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
          AND indexed_parser_version<p_parser_version) THEN manifest_revision ELSE indexed_revision END,
      index_status=CASE WHEN NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects
        WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
          AND indexed_parser_version<p_parser_version) THEN 'ready' ELSE 'pending' END WHERE id=s.id;
END $$;
