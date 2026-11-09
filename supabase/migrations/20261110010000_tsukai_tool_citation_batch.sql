BEGIN;
CREATE OR REPLACE FUNCTION public.tsukai_register_citations_batch(
  p_job_id text,p_attempt_id text,p_citations jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE citation jsonb; numbers jsonb := '[]'::jsonb;
BEGIN
  IF jsonb_typeof(p_citations) IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'invalid citations';
  END IF;
  IF jsonb_array_length(p_citations) > 1000 THEN
    RAISE EXCEPTION 'too many citations';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended(p_job_id || ':' || p_attempt_id, 0));
  FOR citation IN SELECT value FROM jsonb_array_elements(p_citations) LOOP
    IF jsonb_typeof(citation->'source_key') IS DISTINCT FROM 'string'
       OR jsonb_typeof(citation->'source') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'invalid citation';
    END IF;
    numbers := numbers || jsonb_build_array(public.tsukai_register_citation(
      p_job_id,p_attempt_id,citation->>'source_key',citation->'source'
    ));
  END LOOP;
  RETURN numbers;
END $$;
REVOKE ALL ON FUNCTION public.tsukai_register_citations_batch(text,text,jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.tsukai_register_citations_batch(text,text,jsonb) TO service_role;
COMMIT;
