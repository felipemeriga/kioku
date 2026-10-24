-- Manabi credentials are scoped only to machine connection presence.
CREATE TABLE IF NOT EXISTS public.remote_machines (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    id uuid NOT NULL,
    token_hash text NOT NULL,
    name text NOT NULL,
    platform text NOT NULL,
    version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    connected_at timestamptz,
    last_seen timestamptz,
    connected boolean NOT NULL DEFAULT false,
    connection_id uuid,
    PRIMARY KEY (user_id, id)
);
ALTER TABLE public.remote_machines ENABLE ROW LEVEL SECURITY;
-- All access is through authenticated backend routes; no direct client grants.
REVOKE ALL ON public.remote_machines FROM anon, authenticated;
GRANT ALL ON public.remote_machines TO service_role;
