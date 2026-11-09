-- One owner-scoped read preserves each requested repository's independent limit.
BEGIN;
CREATE OR REPLACE FUNCTION public.repo_graph_outline_scope(
 p_owner uuid,p_folders uuid[],p_path text,p_limit integer DEFAULT 500
) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 WITH normalized AS (
  SELECT rtrim(CASE WHEN left(p_path,2)='./' THEN substr(p_path,3) ELSE p_path END,'/') AS path
 )
 SELECT coalesce(jsonb_agg(to_jsonb(result) - 'folder_order' - 'row_order'
                          ORDER BY result.folder_order,result.row_order),'[]'::jsonb)
 FROM (
  SELECT requested.ordinality AS folder_order,hit.*
  FROM normalized
  CROSS JOIN unnest(p_folders) WITH ORDINALITY requested(folder_id,ordinality)
  JOIN public.folders f ON f.id=requested.folder_id AND f.user_id=p_owner
  CROSS JOIN LATERAL (
   SELECT normalized.path NOT IN ('','.') AND EXISTS (
    SELECT 1 FROM public.repo_symbols exact
    WHERE exact.folder_id=f.id AND exact.user_id=p_owner AND exact.file=normalized.path
   ) AS exact_file
  ) mode
  CROSS JOIN LATERAL (
   SELECT limited.*,row_number() OVER (ORDER BY limited.file,limited.start_line) AS row_order
   FROM (
    SELECT s.folder_id,s.node_id,s.symbol,s.kind,s.file,s.start_line,s.updated_at
    FROM public.repo_symbols s
    WHERE s.folder_id=f.id AND s.user_id=p_owner AND (
     (mode.exact_file AND s.file=normalized.path)
     OR (NOT mode.exact_file AND s.file ILIKE
         CASE WHEN normalized.path IN ('','.') THEN '%' ELSE normalized.path || '/%' END)
    )
    ORDER BY s.file,s.start_line LIMIT greatest(0,least(p_limit,500))
   ) limited
  ) hit
 ) result
$$;
REVOKE ALL ON FUNCTION public.repo_graph_outline_scope(uuid,uuid[],text,integer)
 FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.repo_graph_outline_scope(uuid,uuid[],text,integer) TO service_role;
COMMIT;
