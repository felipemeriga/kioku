-- Run as migration owner using psql --set runtime_role=kioku_tsukai_runner -f this-file.
-- Create/provision a dedicated LOGIN role/password separately through private secret storage.
-- This script never accepts or prints a password. Role must not inherit privileged roles.
\set ON_ERROR_STOP on
SELECT 1 / ((NOT rolsuper AND NOT rolbypassrls AND NOT rolinherit
              AND NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid))::int)
FROM pg_roles WHERE rolname = :'runtime_role';
GRANT USAGE ON SCHEMA public TO :"runtime_role";
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO %I', name, :'runtime_role')
FROM unnest(ARRAY['tsukai_jobs','tsukai_attempts','tsukai_events','tsukai_sessions',
                 'tsukai_locks','tsukai_result_acks']) AS name \gexec
SELECT format('CREATE POLICY tsukai_runtime ON public.%I FOR ALL TO %I USING (true) WITH CHECK (true)', name, :'runtime_role')
FROM unnest(ARRAY['tsukai_jobs','tsukai_attempts','tsukai_events','tsukai_sessions',
                 'tsukai_locks','tsukai_result_acks']) AS name \gexec
-- No service_role membership, global BYPASSRLS, schema CREATE, or domain table grants.
