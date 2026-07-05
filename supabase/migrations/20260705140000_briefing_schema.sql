-- Briefing schema for repo folders — Phase 2 of the second-brain reframe.
--
-- Repo folders now hold a strict 8-section briefing instead of the loose
-- {themes, key_facts, gotchas, ...} shape. Each section carries a status
-- (auto/pinned/hybrid), the raw content, and provenance (auto | user_ui |
-- agent_mcp) so an auto-regen can respect user edits and a UI editor can
-- show who last touched what.
--
-- Data model choice: instead of adding one column per section, we store
-- the whole briefing in a single `sections` jsonb column with a well-known
-- shape validated application-side. This keeps schema churn zero as we
-- grow the briefing shape.
--
-- We also relax the kind constraint on folder_summaries to allow
-- 'briefing' — the new kind for repo-briefing rows.
--
-- Rollback: DROP COLUMN + shrink constraint. Existing rows unaffected.

ALTER TABLE public.folder_summaries
    DROP CONSTRAINT IF EXISTS folder_summaries_kind_check;

ALTER TABLE public.folder_summaries
    ADD CONSTRAINT folder_summaries_kind_check
    CHECK (kind IN ('full', 'delta', 'seed', 'workspace_rollup', 'briefing'));

ALTER TABLE public.folder_summaries
    ADD COLUMN IF NOT EXISTS briefing_schema_version int;

ALTER TABLE public.folder_summaries
    ADD COLUMN IF NOT EXISTS sections jsonb;

COMMENT ON COLUMN public.folder_summaries.sections IS
    'For kind=briefing: {overview, architecture, preferences, important_files,
     how_it_runs, deployment, dependencies, activity}. Each section is
     {status, content, provenance, updated_at, updated_by}. Null for
     non-briefing rows.';

COMMENT ON COLUMN public.folder_summaries.briefing_schema_version IS
    'Version of the briefing shape. Bumped when the section structure
     changes so old rows can be upcast or read-only.';
