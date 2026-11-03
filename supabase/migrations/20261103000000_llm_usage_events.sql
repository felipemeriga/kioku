-- One row per completed Anthropic message, including cache-token accounting.
-- List cost is fixed at capture time; unknown models remain unpriced.
CREATE TABLE public.llm_usage_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('chat', 'mihari')),
    operation text NOT NULL,
    folder_id uuid,
    conversation_id uuid,
    response_id uuid,
    round_number integer,
    provider_message_id text NOT NULL UNIQUE,
    model text NOT NULL,
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cache_write_5m_tokens integer NOT NULL DEFAULT 0,
    cache_write_1h_tokens integer NOT NULL DEFAULT 0,
    cache_read_tokens integer NOT NULL DEFAULT 0,
    list_cost_usd numeric(16, 9),
    price_version text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX llm_usage_events_user_created_idx ON public.llm_usage_events (user_id, created_at DESC);
CREATE INDEX llm_usage_events_user_source_idx ON public.llm_usage_events (user_id, source, created_at DESC);
CREATE INDEX llm_usage_events_user_response_idx ON public.llm_usage_events (user_id, response_id);

ALTER TABLE public.llm_usage_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own model usage" ON public.llm_usage_events
    FOR SELECT USING (user_id = auth.uid());
GRANT ALL ON public.llm_usage_events TO service_role;
