CREATE TABLE public.tsukai_native_usage (
  job_id text NOT NULL,
  attempt_id text NOT NULL,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id uuid REFERENCES public.conversations(id) ON DELETE SET NULL,
  message_id uuid REFERENCES public.messages(id) ON DELETE SET NULL,
  outcome text,
  operation text NOT NULL,
  source text NOT NULL,
  model text NOT NULL,
  billing_mode text NOT NULL DEFAULT 'subscription' CHECK(billing_mode='subscription'),
  list_equivalent_usd numeric(20,10),
  complete boolean NOT NULL,
  usage jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(job_id,attempt_id)
);
CREATE INDEX tsukai_native_usage_month ON public.tsukai_native_usage(created_at);
ALTER TABLE public.tsukai_native_usage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tsukai_native_usage FROM anon,authenticated;
GRANT ALL ON public.tsukai_native_usage TO service_role;
