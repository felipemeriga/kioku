-- Preserve the existing shared allocator while avoiding one network RTT per source.
BEGIN;
CREATE OR REPLACE FUNCTION public.tsukai_register_bootstrap_citations(
  p_job_id text,p_attempt_id text,p_citations jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  citation jsonb;
  n integer;
  numbers jsonb := '[]'::jsonb;
BEGIN
  IF jsonb_typeof(p_citations) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'invalid bootstrap citations';
  END IF;
  -- The same namespace lock used by individual registrations protects the whole batch.
  PERFORM pg_advisory_xact_lock(hashtextextended(p_job_id || ':' || p_attempt_id, 0));
  FOR citation IN SELECT value FROM jsonb_array_elements(p_citations) LOOP
    IF jsonb_typeof(citation->'source_key') IS DISTINCT FROM 'string'
       OR jsonb_typeof(citation->'source') IS DISTINCT FROM 'object'
       OR jsonb_typeof(citation->'number') IS DISTINCT FROM 'number' THEN
      RAISE EXCEPTION 'invalid bootstrap citation';
    END IF;
    n := public.tsukai_register_citation(
      p_job_id,p_attempt_id,citation->>'source_key',citation->'source'
    );
    IF n <> (citation->>'number')::integer THEN
      -- A conflict rolls back every registration; never publish misnumbered evidence.
      RAISE EXCEPTION 'Bootstrap citation namespace mismatch';
    END IF;
    numbers := numbers || jsonb_build_array(n);
  END LOOP;
  RETURN numbers;
END $$;
REVOKE ALL ON FUNCTION public.tsukai_register_bootstrap_citations(text,text,jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.tsukai_register_bootstrap_citations(text,text,jsonb) TO service_role;
COMMIT;
