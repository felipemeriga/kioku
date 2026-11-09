DO $$
DECLARE batch jsonb := '[{"source_key":"a","source":{}},{"source_key":"b","source":{}},{"source_key":"a","source":{}}]';
BEGIN
 IF has_function_privilege('anon','public.tsukai_register_citations_batch(text,text,jsonb)','EXECUTE')
 OR has_function_privilege('authenticated','public.tsukai_register_citations_batch(text,text,jsonb)','EXECUTE') THEN
  RAISE EXCEPTION 'batch exposed to clients';
 END IF;
 PERFORM tsukai_register_citation('tool-batch','attempt','existing','{}');
 IF tsukai_register_citations_batch('tool-batch','attempt',batch) <> '[2,3,2]'::jsonb
 OR tsukai_register_citations_batch('tool-batch','attempt',batch) <> '[2,3,2]'::jsonb
 OR tsukai_register_citations_batch('tool-batch','other',batch) <> '[1,2,1]'::jsonb THEN
  RAISE EXCEPTION 'namespace/identity/order mismatch';
 END IF;
 BEGIN
  PERFORM tsukai_register_citations_batch('rollback-batch','attempt',
    '[{"source_key":"a","source":{}},{"source_key":3,"source":{}}]');
  RAISE EXCEPTION 'invalid accepted';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'invalid citation' THEN RAISE; END IF;
 END;
 IF EXISTS(SELECT 1 FROM tsukai_citation_sources WHERE job_id='rollback-batch') THEN
  RAISE EXCEPTION 'partial batch persisted';
 END IF;
END $$;
SET ROLE service_role;
SELECT tsukai_register_citations_batch('service-tool-batch','attempt','[{"source_key":"a","source":{}}]');
RESET ROLE;
