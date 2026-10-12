-- Per-user BYOK (bring-your-own-key) AI provider config. One row per user:
-- their encrypted API keys per provider + the chosen chat model. Keys are
-- KMS-encrypted (services/crypto.encrypt_secret). Reads go through the service
-- role (bypasses RLS) and always filter by user_id; RLS is the backstop.
CREATE TABLE IF NOT EXISTS public.user_ai_config (
    user_id uuid NOT NULL PRIMARY KEY,
    anthropic_key_encrypted text,
    openai_key_encrypted text,
    deepseek_key_encrypted text,
    chat_provider text,
    chat_model text,
    updated_at timestamp with time zone DEFAULT now()
);

ALTER TABLE public.user_ai_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own ai config" ON public.user_ai_config;
CREATE POLICY "Users manage own ai config" ON public.user_ai_config
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
