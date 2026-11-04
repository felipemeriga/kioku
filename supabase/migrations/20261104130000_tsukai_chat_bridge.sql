-- Product-side durable outbox and authoritative evidence for native execution.
CREATE TABLE public.tsukai_chat_turns (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id uuid NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
  request jsonb NOT NULL,
  job_id text UNIQUE,
  state text NOT NULL DEFAULT 'prepared'
    CHECK (state IN ('prepared','submitted','committed','acknowledged','failed','cancelled','uncertain')),
  user_message_id uuid NOT NULL DEFAULT gen_random_uuid(),
  assistant_message_id uuid,
  error_code text,
  cancel_requested boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX tsukai_chat_one_active ON public.tsukai_chat_turns(conversation_id)
  WHERE state IN ('prepared','submitted');
CREATE INDEX tsukai_chat_reconcile ON public.tsukai_chat_turns(state, created_at);
ALTER TABLE public.tsukai_chat_turns ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_chat_turns FROM anon, authenticated;
GRANT ALL ON public.tsukai_chat_turns TO service_role;

CREATE TABLE public.tsukai_tool_traces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  job_id text NOT NULL,
  attempt_id text NOT NULL,
  folder_ids uuid[] NOT NULL,
  trace jsonb NOT NULL,
  result text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tsukai_tool_traces_job ON public.tsukai_tool_traces(job_id, created_at);
ALTER TABLE public.tsukai_tool_traces ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_tool_traces FROM anon, authenticated;
GRANT ALL ON public.tsukai_tool_traces TO service_role;

CREATE TABLE public.tsukai_citation_sources (
  job_id text NOT NULL,
  attempt_id text NOT NULL,
  source_key text NOT NULL,
  number integer NOT NULL,
  source jsonb NOT NULL,
  PRIMARY KEY(job_id,attempt_id,source_key),
  UNIQUE(job_id,attempt_id,number)
);
ALTER TABLE public.tsukai_citation_sources ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_citation_sources FROM anon, authenticated;
GRANT ALL ON public.tsukai_citation_sources TO service_role;

CREATE OR REPLACE FUNCTION public.tsukai_begin_chat_turn(
  p_turn_id uuid, p_owner_id uuid, p_conversation_id uuid, p_request jsonb, p_content text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE existing public.tsukai_chat_turns;
BEGIN
  PERFORM 1 FROM public.conversations
    WHERE id=p_conversation_id AND user_id=p_owner_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'conversation not found' USING ERRCODE='42501'; END IF;
  SELECT * INTO existing FROM public.tsukai_chat_turns WHERE id=p_turn_id;
  IF FOUND THEN
    IF existing.owner_id <> p_owner_id OR existing.conversation_id <> p_conversation_id
       OR existing.request <> p_request THEN
      RAISE EXCEPTION 'turn idempotency conflict' USING ERRCODE='23505';
    END IF;
    RETURN to_jsonb(existing);
  END IF;
  INSERT INTO public.tsukai_chat_turns(id,owner_id,conversation_id,request)
    VALUES(p_turn_id,p_owner_id,p_conversation_id,p_request) RETURNING * INTO existing;
  INSERT INTO public.messages(id,conversation_id,role,content)
    VALUES(existing.user_message_id,p_conversation_id,'user',p_content);
  UPDATE public.conversations SET title=left(p_content,50)
    WHERE id=p_conversation_id AND (title IS NULL OR title='' OR title='New conversation');
  RETURN to_jsonb(existing);
END $$;

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
  IF turn.state IN ('committed','acknowledged') THEN RETURN turn.assistant_message_id; END IF;
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

CREATE OR REPLACE FUNCTION public.tsukai_register_citation(
  p_job_id text,p_attempt_id text,p_source_key text,p_source jsonb
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE n integer;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended(p_job_id || ':' || p_attempt_id, 0));
  SELECT number INTO n FROM public.tsukai_citation_sources
    WHERE job_id=p_job_id AND attempt_id=p_attempt_id AND source_key=p_source_key;
  IF FOUND THEN RETURN n; END IF;
  SELECT coalesce(max(number),0)+1 INTO n FROM public.tsukai_citation_sources
    WHERE job_id=p_job_id AND attempt_id=p_attempt_id;
  INSERT INTO public.tsukai_citation_sources VALUES(p_job_id,p_attempt_id,p_source_key,n,p_source);
  RETURN n;
END $$;
REVOKE ALL ON FUNCTION public.tsukai_begin_chat_turn(uuid,uuid,uuid,jsonb,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.tsukai_commit_chat_turn(uuid,uuid,text,text,jsonb,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.tsukai_register_citation(text,text,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.tsukai_begin_chat_turn(uuid,uuid,uuid,jsonb,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.tsukai_commit_chat_turn(uuid,uuid,text,text,jsonb,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.tsukai_register_citation(text,text,text,jsonb) TO service_role;

-- Parameterized metadata operations replace arbitrary model-generated SQL on the native tool path.
CREATE OR REPLACE FUNCTION public.tsukai_scoped_metadata(
  p_owner_id uuid,p_folder_ids uuid[],p_operation text,
  p_source_type text DEFAULT NULL,p_filename text DEFAULT NULL,
  p_created_after timestamptz DEFAULT NULL,p_created_before timestamptz DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE answer jsonb;
BEGIN
  IF p_operation NOT IN ('count_files','count_chunks','list_files','source_types') THEN
    RAISE EXCEPTION 'unsupported metadata operation';
  END IF;
  IF EXISTS(SELECT 1 FROM unnest(p_folder_ids) AS f(id)
    LEFT JOIN public.folders owned ON owned.id=f.id AND owned.user_id=p_owner_id
    WHERE owned.id IS NULL) THEN RAISE EXCEPTION 'metadata scope revoked'; END IF;
  IF p_operation IN ('count_files','count_chunks') THEN
    SELECT jsonb_build_object('count',CASE WHEN p_operation='count_files'
      THEN count(DISTINCT (folder_id,source_filename)) ELSE count(*) END) INTO answer
    FROM public.documents WHERE user_id=p_owner_id AND folder_id=ANY(p_folder_ids)
      AND (p_source_type IS NULL OR source_type=p_source_type)
      AND (p_filename IS NULL OR source_filename=p_filename)
      AND (p_created_after IS NULL OR created_at>=p_created_after)
      AND (p_created_before IS NULL OR created_at<=p_created_before);
  ELSIF p_operation='source_types' THEN
    SELECT coalesce(jsonb_agg(t),'[]'::jsonb) INTO answer FROM (
      SELECT source_type,count(DISTINCT (folder_id,source_filename)) AS files FROM public.documents
      WHERE user_id=p_owner_id AND folder_id=ANY(p_folder_ids)
        AND (p_source_type IS NULL OR source_type=p_source_type)
        AND (p_filename IS NULL OR source_filename=p_filename)
        AND (p_created_after IS NULL OR created_at>=p_created_after)
        AND (p_created_before IS NULL OR created_at<=p_created_before)
      GROUP BY source_type ORDER BY source_type LIMIT 100) t;
  ELSE
    SELECT coalesce(jsonb_agg(t),'[]'::jsonb) INTO answer FROM (
      SELECT DISTINCT source_filename,source_type,folder_id FROM public.documents
      WHERE user_id=p_owner_id AND folder_id=ANY(p_folder_ids)
        AND (p_source_type IS NULL OR source_type=p_source_type)
        AND (p_filename IS NULL OR source_filename=p_filename)
        AND (p_created_after IS NULL OR created_at>=p_created_after)
        AND (p_created_before IS NULL OR created_at<=p_created_before)
      ORDER BY source_filename LIMIT 200) t;
  END IF;
  RETURN jsonb_build_object('operation',p_operation,'data',answer,
    'limit',CASE WHEN p_operation='list_files' THEN 200 ELSE NULL END);
END $$;
REVOKE ALL ON FUNCTION public.tsukai_scoped_metadata(uuid,uuid[],text,text,text,timestamptz,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.tsukai_scoped_metadata(uuid,uuid[],text,text,text,timestamptz,timestamptz) TO service_role;
