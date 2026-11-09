-- Internal bridge operations accept backend-validated owner scope, not client
-- identity. Remove Supabase's direct schema-default client grants as well as PUBLIC.
BEGIN;
REVOKE ALL ON FUNCTION public.tsukai_begin_chat_turn(uuid,uuid,uuid,jsonb,text),
  public.tsukai_commit_chat_turn(uuid,uuid,text,text,jsonb,jsonb),
  public.tsukai_scoped_metadata(uuid,uuid[],text,text,text,timestamptz,timestamptz)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.tsukai_begin_chat_turn(uuid,uuid,uuid,jsonb,text),
  public.tsukai_commit_chat_turn(uuid,uuid,text,text,jsonb,jsonb),
  public.tsukai_scoped_metadata(uuid,uuid[],text,text,text,timestamptz,timestamptz)
  TO service_role;
DO $$
DECLARE name text;
BEGIN
  FOREACH name IN ARRAY ARRAY['tsukai_account_deleted', 'tsukai_conversation_deleted'] LOOP
    IF to_regprocedure('public.' || name || '()') IS NOT NULL THEN
      EXECUTE format('REVOKE ALL ON FUNCTION public.%I() FROM PUBLIC, anon, authenticated', name);
    END IF;
  END LOOP;
END $$;
COMMIT;
