-- Follow-up for briefing rollout: relax the trigger constraint on
-- folder_summaries so briefing edits (from UI + MCP) can be persisted
-- with meaningful trigger labels, AND make sure the kind constraint
-- includes 'briefing' + 'workspace_rollup' if either was missed.
--
-- If both are already applied this is a no-op (constraints are dropped
-- and re-added identically).

ALTER TABLE public.folder_summaries
    DROP CONSTRAINT IF EXISTS folder_summaries_trigger_check;

ALTER TABLE public.folder_summaries
    ADD CONSTRAINT folder_summaries_trigger_check CHECK (
        trigger IS NULL
        OR trigger IN (
            'cron_nightly',
            'cron_weekly',
            'manual',
            'seed',
            'edit',        -- UI section edit (Save + Pin)
            'mcp_edit',    -- MCP update_folder_briefing_section
            'rollup_bootstrap:manual',
            'rollup_bootstrap:cron_nightly',
            'rollup_bootstrap:cron_weekly'
        )
    );

-- Re-verify the kind constraint too — safe to run repeatedly.
ALTER TABLE public.folder_summaries
    DROP CONSTRAINT IF EXISTS folder_summaries_kind_check;

ALTER TABLE public.folder_summaries
    ADD CONSTRAINT folder_summaries_kind_check
    CHECK (kind IN ('full', 'delta', 'seed', 'workspace_rollup', 'briefing'));
