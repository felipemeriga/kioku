-- Supabase can grant schema-default privileges directly; revoking PUBLIC alone
-- does not remove those grants from internal SECURITY DEFINER functions.
BEGIN;
REVOKE ALL ON FUNCTION public.tsukai_register_citation(text,text,text,jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.tsukai_register_citation(text,text,text,jsonb) TO service_role;
COMMIT;
