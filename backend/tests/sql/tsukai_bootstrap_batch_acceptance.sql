DO $$
DECLARE citations jsonb := '[
  {"source_key":"first","number":1,"source":{"owner_id":"owner"}},
  {"source_key":"second","number":2,"source":{"owner_id":"owner"}}
]'::jsonb;
BEGIN
  IF has_function_privilege('anon',
       'public.tsukai_register_bootstrap_citations(text,text,jsonb)','EXECUTE')
     OR has_function_privilege('authenticated',
       'public.tsukai_register_bootstrap_citations(text,text,jsonb)','EXECUTE') THEN
    RAISE EXCEPTION 'bootstrap allocator exposed to clients';
  END IF;
  IF NOT has_function_privilege('service_role',
       'public.tsukai_register_bootstrap_citations(text,text,jsonb)','EXECUTE') THEN
    RAISE EXCEPTION 'service allocator unavailable';
  END IF;
  IF tsukai_register_bootstrap_citations('batch-job','attempt',citations) <> '[1,2]'::jsonb
     OR tsukai_register_bootstrap_citations('batch-job','attempt',citations) <> '[1,2]'::jsonb THEN
    RAISE EXCEPTION 'batch remint changed citation numbers';
  END IF;
  IF tsukai_register_citation('batch-job','attempt','later','{}') <> 3 THEN
    RAISE EXCEPTION 'batch failed to share the MCP allocator';
  END IF;
  IF tsukai_register_bootstrap_citations('batch-job','other-attempt',citations) <> '[1,2]'::jsonb THEN
    RAISE EXCEPTION 'attempt namespace leaked';
  END IF;
  BEGIN
    PERFORM tsukai_register_bootstrap_citations('conflict-job','attempt',
      '[{"source_key":"first","number":1,"source":{}},
        {"source_key":"second","number":9,"source":{}}]');
    RAISE EXCEPTION 'namespace conflict accepted';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'Bootstrap citation namespace mismatch' THEN RAISE; END IF;
  END;
  IF EXISTS(SELECT 1 FROM tsukai_citation_sources WHERE job_id='conflict-job') THEN
    RAISE EXCEPTION 'partially registered conflicting bootstrap';
  END IF;
  BEGIN
    PERFORM tsukai_register_bootstrap_citations('invalid-job','attempt','null');
    RAISE EXCEPTION 'invalid input accepted';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'invalid bootstrap citations' THEN RAISE; END IF;
  END;
END $$;

-- Exercise the actual restricted caller, not just an administrator's privilege lookup.
SET ROLE service_role;
SELECT tsukai_register_bootstrap_citations('service-job','attempt',
  '[{"source_key":"first","number":1,"source":{}}]');
RESET ROLE;
