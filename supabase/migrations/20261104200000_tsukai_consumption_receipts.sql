-- An immutable publication identity survives every subsequent lifecycle state.
CREATE OR REPLACE FUNCTION public.tsukai_commit_chat_turn(
  p_turn_id uuid,p_owner_id uuid,p_job_id text,p_content text,p_debug jsonb,p_citations jsonb
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE turn public.tsukai_chat_turns; message_id uuid;
BEGIN
  SELECT * INTO turn FROM public.tsukai_chat_turns
    WHERE id=p_turn_id AND owner_id=p_owner_id FOR UPDATE;
  IF NOT FOUND OR turn.job_id IS DISTINCT FROM p_job_id THEN
    RAISE EXCEPTION 'execution ownership conflict' USING ERRCODE='42501';
  END IF;
  PERFORM 1 FROM public.conversations WHERE id=turn.conversation_id AND user_id=p_owner_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'conversation removed' USING ERRCODE='42501'; END IF;
  IF turn.assistant_message_id IS NOT NULL THEN RETURN turn.assistant_message_id; END IF;
  IF turn.state <> 'submitted' OR length(trim(p_content))=0 THEN
    RAISE EXCEPTION 'invalid publication state';
  END IF;
  message_id := gen_random_uuid();
  INSERT INTO public.messages(id,conversation_id,role,content,debug,citations)
    VALUES(message_id,turn.conversation_id,'assistant',p_content,p_debug,p_citations);
  UPDATE public.tsukai_chat_turns SET state='committed',assistant_message_id=message_id,
    updated_at=now() WHERE id=p_turn_id;
  RETURN message_id;
END $$;

CREATE TABLE public.tsukai_completion_receipts (
  job_id text PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id uuid REFERENCES public.conversations(id) ON DELETE CASCADE,
  scope jsonb NOT NULL,
  operation text NOT NULL,
  profile text NOT NULL,
  consumer text NOT NULL,
  reference text NOT NULL,
  payload jsonb NOT NULL,
  acknowledged boolean NOT NULL DEFAULT false,
  processed boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_attempt_at timestamptz NOT NULL DEFAULT 'epoch'
);
ALTER TABLE public.tsukai_completion_receipts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_completion_receipts FROM anon,authenticated;
GRANT ALL ON public.tsukai_completion_receipts TO service_role;
ALTER TABLE public.tsukai_domain_deletions ADD COLUMN last_attempt_at timestamptz NOT NULL DEFAULT 'epoch';
