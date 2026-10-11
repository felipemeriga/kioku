-- Enable Row-Level Security on every remaining public table.
--
-- The app only ever touches these tables via the Supabase SERVICE ROLE
-- (backend + watcher) or the superuser pooler connection (mem0) — both of which
-- BYPASS RLS. The frontend never queries tables directly (it uses Supabase only
-- for auth). So this is pure defense-in-depth: it denies any direct
-- anon/authenticated PostgREST access to these tables.

-- User-scoped tables → owner-only policy (same scheme as the existing tables).
ALTER TABLE public.user_git_keys ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own git keys" ON public.user_git_keys;
CREATE POLICY "Users manage own git keys" ON public.user_git_keys
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE public.watched_repos ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own watched repos" ON public.watched_repos;
CREATE POLICY "Users manage own watched repos" ON public.watched_repos
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE public.code_chunks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own code chunks" ON public.code_chunks;
CREATE POLICY "Users manage own code chunks" ON public.code_chunks
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

ALTER TABLE public.repo_freshness ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Users manage own repo freshness" ON public.repo_freshness;
CREATE POLICY "Users manage own repo freshness" ON public.repo_freshness
  USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());

-- Internal tables (no user_id; only touched by service-role / superuser
-- connections): enable RLS with no policy → denies anon/authenticated.
ALTER TABLE public.memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_blobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_writes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.checkpoint_migrations ENABLE ROW LEVEL SECURITY;
