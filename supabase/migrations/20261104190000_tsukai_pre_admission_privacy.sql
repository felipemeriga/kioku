-- Plain retrieval may finish before turn admission. Its privacy attribution
-- must not depend on a mapping row that has not yet been inserted.
CREATE OR REPLACE FUNCTION public.tsukai_conversation_deleted()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
  INSERT INTO public.tsukai_domain_deletions(owner_id,conversation_id,kind)
    VALUES(OLD.user_id,OLD.id,'conversation') ON CONFLICT DO NOTHING;
  DELETE FROM public.tsukai_tool_traces WHERE trace->>'conversation_id'=OLD.id::text OR job_id IN
    (SELECT job_id FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id)
    OR job_id IN (SELECT id::text FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id);
  DELETE FROM public.tsukai_citation_sources WHERE source->>'conversation_id'=OLD.id::text OR job_id IN
    (SELECT job_id FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id)
    OR job_id IN (SELECT id::text FROM public.tsukai_chat_turns WHERE conversation_id=OLD.id);
  RETURN OLD;
END $$;
CREATE OR REPLACE FUNCTION public.tsukai_account_deleted()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
  INSERT INTO public.tsukai_domain_deletions(owner_id,kind)
    VALUES(OLD.id,'account') ON CONFLICT DO NOTHING;
  DELETE FROM public.tsukai_citation_sources WHERE source->>'owner_id'=OLD.id::text OR job_id IN
    (SELECT job_id FROM public.tsukai_chat_turns WHERE owner_id=OLD.id)
    OR job_id IN (SELECT id::text FROM public.tsukai_chat_turns WHERE owner_id=OLD.id);
  RETURN OLD;
END $$;
