-- Workspace rollup summaries for container folders (Idea C).
--
-- A container folder is one whose direct doc count is small but has
-- subfolders — think 'cosm' in a workspace where the real content lives
-- under c360-lead/, h265/, nba/, etc. Its summary should be a rollup of
-- its children's summaries, not a summary of its own (nearly empty)
-- doc set.
--
-- Changes:
--   1. Allow kind='workspace_rollup' in folder_summaries.
--   2. Add subfolder_snapshots jsonb column tracking which child-summary
--      IDs were rolled up. Populated for workspace_rollup rows; null for
--      leaf-folder full/delta/seed rows. Used by auto-mode to detect
--      when any child summary has moved forward → parent is stale.
--
-- Rollback: drop the column and shrink the check constraint back down.
-- No data migration needed — existing rows have subfolder_snapshots null
-- and the constraint is a strict superset.

ALTER TABLE public.folder_summaries
    DROP CONSTRAINT IF EXISTS folder_summaries_kind_check;

ALTER TABLE public.folder_summaries
    ADD CONSTRAINT folder_summaries_kind_check
    CHECK (kind IN ('full', 'delta', 'seed', 'workspace_rollup'));

ALTER TABLE public.folder_summaries
    ADD COLUMN IF NOT EXISTS subfolder_snapshots jsonb;

COMMENT ON COLUMN public.folder_summaries.subfolder_snapshots IS
    'For workspace_rollup rows: {child_folder_id: latest_summary_id_at_rollup_time}.
     Auto-mode detects staleness by comparing this map against the current
     latest summary per child. Null for leaf-folder rows.';
