-- Calendar activity is indexed native event time, rolled up to original root sessions.
CREATE INDEX agent_evidence_calendar_events ON public.agent_evidence_events
    (user_id, folder_id, event_at, session_id) WHERE displayable AND NOT inherited;

CREATE OR REPLACE FUNCTION public.agent_history_days(
    p_user_id uuid,p_folder_id uuid,p_from date,p_to date,p_timezone text,p_agent text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
    IF p_to<p_from OR p_to-p_from>62 OR p_agent NOT IN ('codex','claude_code') THEN
        RAISE EXCEPTION 'evidence_invalid_calendar_range';
    END IF;
    WITH activity AS (
      SELECT (e.event_at AT TIME ZONE p_timezone)::date AS day,root.id AS root_id,root.agent
      FROM public.agent_evidence_events e
      JOIN public.agent_evidence_sessions source ON source.id=e.session_id
      JOIN public.agent_evidence_sessions root ON root.id=source.root_session_id
      WHERE e.user_id=p_user_id AND e.folder_id=p_folder_id
        AND source.user_id=p_user_id AND source.folder_id=p_folder_id AND source.deleted_at IS NULL
        AND root.user_id=p_user_id AND root.folder_id=p_folder_id AND root.deleted_at IS NULL
        AND root.parent_session_id IS NULL AND (p_agent IS NULL OR root.agent=p_agent)
        AND e.displayable AND NOT e.inherited
        AND e.event_at >= p_from::timestamp AT TIME ZONE p_timezone
        AND e.event_at < (p_to+1)::timestamp AT TIME ZONE p_timezone
    ), daily AS (
      SELECT day,count(DISTINCT root_id) AS session_count,count(*) AS event_count,
        array_agg(DISTINCT agent ORDER BY agent) AS agents FROM activity GROUP BY day
    ) SELECT COALESCE(jsonb_agg(jsonb_build_object('date',day,'session_count',session_count,
        'event_count',event_count,'agents',agents) ORDER BY day),'[]') INTO result FROM daily;
    RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.agent_history_sessions(
    p_user_id uuid,p_folder_id uuid,p_date date,p_timezone text,p_limit integer,
    p_before_at timestamptz DEFAULT NULL,p_before_id uuid DEFAULT NULL,p_agent text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
    IF p_limit<1 OR p_limit>101 OR p_agent NOT IN ('codex','claude_code') THEN
        RAISE EXCEPTION 'evidence_invalid_calendar_range';
    END IF;
    WITH activity AS (
      SELECT root.id AS root_id,e.event_at,e.event_id,e.session_id,e.position
      FROM public.agent_evidence_events e
      JOIN public.agent_evidence_sessions source ON source.id=e.session_id
      JOIN public.agent_evidence_sessions root ON root.id=source.root_session_id
      WHERE e.user_id=p_user_id AND e.folder_id=p_folder_id
        AND source.user_id=p_user_id AND source.folder_id=p_folder_id AND source.deleted_at IS NULL
        AND root.user_id=p_user_id AND root.folder_id=p_folder_id AND root.deleted_at IS NULL
        AND root.parent_session_id IS NULL AND (p_agent IS NULL OR root.agent=p_agent)
        AND e.displayable AND NOT e.inherited
        AND e.event_at >= p_date::timestamp AT TIME ZONE p_timezone
        AND e.event_at < (p_date+1)::timestamp AT TIME ZONE p_timezone
    ), daily AS (
      SELECT root_id,min(event_at) AS first_at,max(event_at) AS last_at,count(*) AS event_count,
        (array_agg(event_id ORDER BY event_at,position,event_id))[1] AS first_event_id,
        (array_agg(session_id ORDER BY event_at,position,event_id))[1] AS first_session_id
      FROM activity GROUP BY root_id
    ), page AS (
      SELECT * FROM daily WHERE p_before_at IS NULL OR (last_at,root_id)<(p_before_at,p_before_id)
      ORDER BY last_at DESC,root_id DESC LIMIT p_limit
    ), children AS (
      SELECT child.parent_session_id,jsonb_agg(jsonb_build_object('id',child.id,'agent',child.agent,
        'native_session_id',child.native_session_id,'event_count',child.event_count) ORDER BY child.id) AS items
      FROM public.agent_evidence_sessions child JOIN page ON child.parent_session_id=page.root_id
      WHERE child.user_id=p_user_id AND child.folder_id=p_folder_id AND child.deleted_at IS NULL
      GROUP BY child.parent_session_id
    ) SELECT COALESCE(jsonb_agg(jsonb_build_object(
      'id',root.id,'agent',root.agent,'native_session_id',root.native_session_id,
      'parent_session_id',root.parent_session_id,'root_session_id',root.root_session_id,
      'title',NULL,'summary',NULL,'first_event_at',root.first_event_at,'last_event_at',root.last_event_at,
      'manifest_revision',root.manifest_revision,'indexed_revision',root.indexed_revision,
      'capture_status',root.capture_status,'index_status',root.index_status,'event_count',root.event_count,
      'gaps',root.gaps,'children',COALESCE(children.items,'[]'),
      'day_first_event_at',page.first_at,'day_last_event_at',page.last_at,
      'day_event_count',page.event_count,'day_first_event_id',page.first_event_id,
      'day_first_session_id',page.first_session_id) ORDER BY page.last_at DESC,page.root_id DESC),'[]')
      INTO result FROM page JOIN public.agent_evidence_sessions root ON root.id=page.root_id
      LEFT JOIN children ON children.parent_session_id=root.id;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.agent_history_days(uuid,uuid,date,date,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.agent_history_sessions(uuid,uuid,date,text,integer,timestamptz,uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.agent_history_days(uuid,uuid,date,date,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.agent_history_sessions(uuid,uuid,date,text,integer,timestamptz,uuid,text) TO service_role;
