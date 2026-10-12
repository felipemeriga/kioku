-- Per-turn chat token usage, for the Settings usage/cost view. Going-forward
-- only (one row per chat turn, written by stream_rag_response).
CREATE TABLE IF NOT EXISTS public.chat_usage (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    user_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    model text NOT NULL,
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_usage_user_created_idx ON public.chat_usage (user_id, created_at);
CREATE INDEX IF NOT EXISTS chat_usage_user_conversation_idx ON public.chat_usage (user_id, conversation_id);

-- Owner-only, matching every other user-data table. The app reads via the
-- service role (bypasses RLS) and always filters by user_id; this is the
-- defense-in-depth backstop against direct anon/authenticated access.
ALTER TABLE public.chat_usage ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own chat usage" ON public.chat_usage;
CREATE POLICY "Users manage own chat usage" ON public.chat_usage
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
