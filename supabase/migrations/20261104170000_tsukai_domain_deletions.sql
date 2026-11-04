-- No owner FK: the durable deletion intent must survive account cascades.
CREATE TABLE public.tsukai_domain_deletions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL,
  conversation_id uuid,
  kind text NOT NULL CHECK(kind IN ('conversation','account')),
  state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','submitted','cleaned')),
  tombstone_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX tsukai_domain_delete_conversation
  ON public.tsukai_domain_deletions(owner_id,conversation_id) WHERE kind='conversation';
CREATE UNIQUE INDEX tsukai_domain_delete_account
  ON public.tsukai_domain_deletions(owner_id) WHERE kind='account';
ALTER TABLE public.tsukai_domain_deletions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_domain_deletions FROM anon,authenticated;
GRANT ALL ON public.tsukai_domain_deletions TO service_role;

CREATE OR REPLACE FUNCTION public.tsukai_conversation_deleted()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
  INSERT INTO public.tsukai_domain_deletions(owner_id,conversation_id,kind)
    VALUES(OLD.user_id,OLD.id,'conversation') ON CONFLICT DO NOTHING;
  DELETE FROM public.tsukai_tool_traces WHERE job_id IN
    (SELECT job_id FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id)
    OR job_id IN (SELECT id::text FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id);
  DELETE FROM public.tsukai_citation_sources WHERE job_id IN
    (SELECT job_id FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id)
    OR job_id IN (SELECT id::text FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id);
  RETURN OLD;
END $$;
CREATE TRIGGER tsukai_conversation_delete BEFORE DELETE ON public.conversations
  FOR EACH ROW EXECUTE FUNCTION public.tsukai_conversation_deleted();

CREATE OR REPLACE FUNCTION public.tsukai_account_deleted()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
  INSERT INTO public.tsukai_domain_deletions(owner_id,kind)
    VALUES(OLD.id,'account') ON CONFLICT DO NOTHING;
  DELETE FROM public.tsukai_citation_sources WHERE job_id IN
    (SELECT job_id FROM public.tsukai_chat_turns WHERE owner_id=OLD.id)
    OR job_id IN (SELECT id::text FROM public.tsukai_chat_turns WHERE owner_id=OLD.id);
  RETURN OLD;
END $$;
CREATE TRIGGER tsukai_account_delete BEFORE DELETE ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.tsukai_account_deleted();
REVOKE ALL ON FUNCTION public.tsukai_conversation_deleted() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.tsukai_account_deleted() FROM PUBLIC;
