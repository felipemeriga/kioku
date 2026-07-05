-- Folder kinds — Phase 1 of the second-brain reframe.
--
-- Every folder is now either a generic 'folder' (default) or a 'repo'
-- (bound to a GitHub sync config, holds the strict 8-section briefing).
-- Only repos can wire Mem0 — enforced application-side. Notion + GitHub
-- can still attach to either kind, though Notion on a repo is unusual.
--
-- Turning a folder into a repo = the GitHub Connect flow flips kind to
-- 'repo' on success. Disconnecting a repo flips it back to 'folder'.
--
-- Backfill: any folder that already has a github_sync_configs row →
-- kind='repo'. Everything else stays 'folder'. Safe: the backfill runs
-- once, is idempotent, and the default handles new rows.
--
-- Rollback: DROP COLUMN. No data loss — kind is derivable from
-- github_sync_configs presence at any time.

ALTER TABLE public.folders
    ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'folder'
    CHECK (kind IN ('folder', 'repo'));

-- Backfill: anything already synced to GitHub is a repo.
UPDATE public.folders f
SET kind = 'repo'
WHERE EXISTS (
    SELECT 1 FROM public.github_sync_configs g
    WHERE g.root_folder_id = f.id
) AND f.kind = 'folder';

COMMENT ON COLUMN public.folders.kind IS
    'folder|repo. Repos bind to a github_sync_configs row and carry the
     strict 8-section briefing schema. Only repos may wire Mem0.';
