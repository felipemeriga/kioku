-- execute_readonly_query is SECURITY DEFINER (runs as postgres, bypassing RLS)
-- and executes an arbitrary caller-supplied SELECT. It was callable by PUBLIC
-- (the Postgres default for new functions) plus explicit anon/authenticated
-- grants — i.e. anyone holding the public anon key could call it directly over
-- PostgREST and read every user's data, RLS bypassed.
--
-- Only the backend (service_role) should ever call it. Revoke everyone else.
REVOKE ALL ON FUNCTION public.execute_readonly_query(text) FROM PUBLIC, anon, authenticated;
