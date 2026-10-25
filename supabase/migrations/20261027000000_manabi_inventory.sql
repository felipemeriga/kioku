-- Current configured-repository inventory only; no agent sessions or memories.
ALTER TABLE public.remote_machines
    ADD COLUMN IF NOT EXISTS custom_name text,
    ADD COLUMN IF NOT EXISTS os_name text,
    ADD COLUMN IF NOT EXISTS os_id text,
    ADD COLUMN IF NOT EXISTS architecture text,
    ADD COLUMN IF NOT EXISTS inventory jsonb,
    ADD COLUMN IF NOT EXISTS inventory_updated_at timestamptz,
    ADD COLUMN IF NOT EXISTS warnings jsonb NOT NULL DEFAULT '[]'::jsonb;
