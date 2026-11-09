DO $$
DECLARE owner uuid := '11111111-1111-1111-1111-111111111111';
 folder uuid; path text; normalized text; result jsonb; expected jsonb; part jsonb;
 folders uuid[] := ARRAY['00000000-0000-0000-0000-000000000002',
 '00000000-0000-0000-0000-000000000004','00000000-0000-0000-0000-000000000001',
 '00000000-0000-0000-0000-000000000003','00000000-0000-0000-0000-000000000099']::uuid[];
BEGIN
 IF has_function_privilege('anon','public.repo_graph_outline_scope(uuid,uuid[],text,integer)','EXECUTE')
 OR has_function_privilege('authenticated','public.repo_graph_outline_scope(uuid,uuid[],text,integer)','EXECUTE')
 OR NOT has_function_privilege('service_role','public.repo_graph_outline_scope(uuid,uuid[],text,integer)','EXECUTE')
 THEN RAISE EXCEPTION 'invalid outline permissions'; END IF;
 FOREACH path IN ARRAY ARRAY['a.ts','a.tsx','A.ts','./a.ts/','src','./src/','src/',
 'src-other','SRC/a.ts','Src/a.ts','Sr_/','missing','.','','./','././src/'] LOOP
  normalized := rtrim(CASE WHEN left(path,2)='./' THEN substr(path,3) ELSE path END,'/');
  expected := '[]';
  FOREACH folder IN ARRAY folders LOOP
   part := '[]';
   IF normalized NOT IN ('','.') THEN
    SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY start_line),'[]') INTO part FROM (
     SELECT s.folder_id,s.node_id,s.symbol,s.kind,s.file,s.start_line,s.updated_at
     FROM repo_symbols s JOIN public.folders f ON f.id=s.folder_id
     WHERE s.folder_id=folder AND s.user_id=owner AND f.user_id=owner AND s.file=normalized
     ORDER BY s.start_line LIMIT 500
    ) q;
   END IF;
   IF part='[]' THEN
    SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY file,start_line),'[]') INTO part FROM (
     SELECT s.folder_id,s.node_id,s.symbol,s.kind,s.file,s.start_line,s.updated_at
     FROM repo_symbols s JOIN public.folders f ON f.id=s.folder_id
     WHERE s.folder_id=folder AND s.user_id=owner AND f.user_id=owner AND s.file ILIKE
      CASE WHEN normalized IN ('','.') THEN '%' ELSE normalized||'/%' END
     ORDER BY s.file,s.start_line LIMIT 500
    ) q;
   END IF;
   expected := expected || part;
  END LOOP;
  result := repo_graph_outline_scope(owner,folders,path,500);
  IF result<>expected THEN RAISE EXCEPTION 'outline differs from independent per-folder reads: %',path; END IF;
 END LOOP;
 IF jsonb_array_length(repo_graph_outline_scope(owner,folders,'.',500))<>1000
 OR jsonb_array_length(repo_graph_outline_scope(owner,folders,'.',1))<>2
 OR repo_graph_outline_scope(owner,'{}','src/',500)<>'[]'
 OR repo_graph_outline_scope(owner,folders,'src/',0)<>'[]'
 OR jsonb_array_length(repo_graph_outline_scope('22222222-2222-2222-2222-222222222222',folders,'.',500))<>500
 THEN RAISE EXCEPTION 'scope/limit mismatch'; END IF;
END $$;
SET ROLE service_role;
SELECT public.repo_graph_outline_scope('11111111-1111-1111-1111-111111111111','{}','src/',500);
RESET ROLE;
