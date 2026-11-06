-- Accept the session ID prefixes displayed on History cards.
CREATE OR REPLACE FUNCTION public.search_agent_history(p_user_id uuid,p_folder_id uuid,p_pattern text DEFAULT '',p_fields text DEFAULT 'all',p_first date DEFAULT NULL,p_last date DEFAULT NULL,p_agent text DEFAULT NULL,p_session text DEFAULT NULL,p_timezone text DEFAULT 'UTC',p_limit integer DEFAULT 20,p_offset integer DEFAULT 0,p_snippet text DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public SET statement_timeout='3s' AS $$
WITH latest AS MATERIALIZED (
 SELECT DISTINCT ON(agent,session_id) agent,session_id,title,summary
 FROM public.agent_journal_search_entries e WHERE user_id=p_user_id AND folder_id=p_folder_id
 AND EXISTS (SELECT 1 FROM public.agent_journal_days d WHERE d.user_id=e.user_id AND d.folder_id=e.folder_id AND d.journal_date=e.journal_date AND d.search_sha256=d.content_sha256)
 ORDER BY agent,session_id,captured_at DESC,entry_id DESC
), candidates AS MATERIALIZED (
 SELECT DISTINCT agent,session_id FROM public.agent_journal_search_entries
 WHERE user_id=p_user_id AND folder_id=p_folder_id AND
 (p_pattern='' OR title ~* p_pattern OR (p_fields='all' AND (summary ~* p_pattern OR body ~* p_pattern)))
), scoped AS MATERIALIZED (
 SELECT e.*,l.title AS current_title,l.summary AS current_summary,
 (e.captured_at AT TIME ZONE p_timezone)::date AS local_date,
 p_pattern<>'' AND l.title ~* p_pattern AS title_hit,
 p_pattern<>'' AND p_fields='all' AND l.summary ~* p_pattern AS overview_hit,
 p_pattern<>'' AND p_fields='all' AND e.body ~* p_pattern AS body_hit
 FROM public.agent_journal_search_entries e JOIN latest l USING(agent,session_id) JOIN candidates c USING(agent,session_id)
 WHERE user_id=p_user_id AND folder_id=p_folder_id
 AND EXISTS (SELECT 1 FROM public.agent_journal_days d WHERE d.user_id=e.user_id AND d.folder_id=e.folder_id AND d.journal_date=e.journal_date AND d.search_sha256=d.content_sha256)
 AND (p_agent IS NULL OR e.agent=p_agent) AND (p_session IS NULL OR starts_with(e.session_id,p_session))
 AND (p_first IS NULL OR e.captured_at >= p_first::timestamp AT TIME ZONE p_timezone)
 AND (p_last IS NULL OR e.captured_at < (p_last+1)::timestamp AT TIME ZONE p_timezone)
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY agent,session_id,body_hit ORDER BY captured_at DESC,entry_id) AS match_rank FROM scoped
), grouped AS (
 SELECT agent,session_id,max(current_title) title,max(current_summary) summary,
 bool_or(title_hit) title_match,bool_or(overview_hit) overview_match,
 count(*) entry_count,count(*) FILTER(WHERE body_hit) matching_entry_count,
 array_agg(DISTINCT local_date ORDER BY local_date) dates,
 array_agg(DISTINCT local_date ORDER BY local_date) FILTER(WHERE body_hit) matching_dates,
 max(captured_at) last_at,
 coalesce(jsonb_agg(jsonb_build_object('id',entry_id,'date',local_date,'captured_at',captured_at,
 'excerpt',substring(body FROM greatest(1,coalesce(nullif(strpos(lower(body),lower(coalesce(p_snippet,substring(body from p_pattern)))),0),1)-100) FOR 500)) ORDER BY captured_at DESC,entry_id) FILTER(WHERE body_hit AND match_rank<=5),'[]') matches
 FROM ranked GROUP BY agent,session_id
 HAVING p_pattern='' OR bool_or(title_hit OR overview_hit OR body_hit)
), page AS (SELECT * FROM grouped ORDER BY last_at DESC,agent,session_id LIMIT greatest(1,least(p_limit,50)) OFFSET greatest(0,least(p_offset,10000)))
SELECT jsonb_build_object('sessions',coalesce((SELECT jsonb_agg(to_jsonb(page) ORDER BY last_at DESC,agent,session_id) FROM page),'[]'),
 'total_sessions',(SELECT count(*) FROM grouped),'total_entries',(SELECT coalesce(sum(matching_entry_count),0) FROM grouped),
 'has_more',(SELECT count(*) FROM grouped)>p_offset+p_limit,
 'coverage',jsonb_build_object('indexed_days',(SELECT count(*) FROM public.agent_journal_days WHERE user_id=p_user_id AND folder_id=p_folder_id AND search_sha256=content_sha256),
 'pending_days',(SELECT count(*) FROM public.agent_journal_days WHERE user_id=p_user_id AND folder_id=p_folder_id AND search_sha256 IS DISTINCT FROM content_sha256)))
$$;
REVOKE ALL ON FUNCTION public.search_agent_history(uuid,uuid,text,text,date,date,text,text,text,integer,integer,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.search_agent_history(uuid,uuid,text,text,date,date,text,text,text,integer,integer,text) TO service_role;

