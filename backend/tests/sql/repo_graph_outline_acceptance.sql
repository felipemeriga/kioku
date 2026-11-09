DO $$
DECLARE owner uuid := '11111111-1111-1111-1111-111111111111';
 folder uuid; path text; result jsonb; expected jsonb; part jsonb;
 folders uuid[] := ARRAY['00000000-0000-0000-0000-000000000002',
 '00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000001',
 '00000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000099']::uuid[];
BEGIN
 IF has_function_privilege('anon','public.repo_graph_outline_scope(uuid,uuid[],text,integer)','EXECUTE')
 OR has_function_privilege('authenticated','public.repo_graph_outline_scope(uuid,uuid[],text,integer)','EXECUTE')
 OR NOT has_function_privilege('service_role','public.repo_graph_outline_scope(uuid,uuid[],text,integer)','EXECUTE')
 THEN RAISE EXCEPTION 'invalid outline permissions'; END IF;
 FOREACH path IN ARRAY ARRAY['src/','SRC/a.ts','Sr_/a%','missing'] LOOP
  expected := '[]';
  FOREACH folder IN ARRAY folders LOOP
   SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY file,start_line),'[]') INTO part FROM (
    SELECT s.folder_id,s.node_id,s.symbol,s.kind,s.file,s.start_line,s.updated_at
    FROM repo_symbols s JOIN public.folders f ON f.id=s.folder_id
    WHERE s.folder_id=folder AND s.user_id=owner AND f.user_id=owner AND s.file ILIKE path||'%'
    ORDER BY s.file,s.start_line LIMIT 500
   ) q;
   expected := expected || part;
  END LOOP;
  result := repo_graph_outline_scope(owner,folders,path,500);
  IF result<>expected THEN RAISE EXCEPTION 'outline differs from independent per-folder reads: %',path; END IF;
 END LOOP;
 IF jsonb_array_length(repo_graph_outline_scope(owner,folders,'src/',500))<>1000
 OR jsonb_array_length(repo_graph_outline_scope(owner,folders,'src/',1))<>2
 OR repo_graph_outline_scope(owner,'{}','src/',500)<>'[]'
 OR repo_graph_outline_scope(owner,folders,'src/',0)<>'[]'
 OR jsonb_array_length(repo_graph_outline_scope('22222222-2222-2222-2222-222222222222',folders,'src/',500))<>500
 THEN RAISE EXCEPTION 'scope/limit mismatch'; END IF;
END $$;
SET ROLE service_role;
SELECT public.repo_graph_outline_scope('11111111-1111-1111-1111-111111111111','{}','src/',500);
RESET ROLE;
