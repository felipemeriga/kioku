-- Local-clone-based GitHub sync.
--
-- The old model: PAT-per-config + hit GitHub API on every populator call.
-- New model: one local clone per (folder, repo), fetched on demand at
-- summary time. No PATs, no polling, no org-policy fights.
--
-- Schema changes:
--   - sync_mode: how the clone gets its credentials.
--       'public'     — HTTPS clone, no auth (public repos)
--       'deploy_key' — SSH clone using a per-repo deploy key
--       'token'      — legacy PAT path (kept for backward compat during
--                      migration; new configs should never write this)
--   - deploy_key_public         — the OpenSSH-format public key we ask
--                                 the user to paste into repo Settings
--                                 → Deploy Keys.
--   - deploy_key_private_encrypted — the private half, encrypted at rest
--                                    the same way tokens are.
--   - local_clone_path — absolute path to the clone on the Kioku host.
--                        Set once at connect time; null until clone
--                        succeeds.
--   - last_fetched_at  — last successful `git fetch` timestamp. Used
--                        to surface staleness in the briefing.

ALTER TABLE github_sync_configs
  ADD COLUMN IF NOT EXISTS sync_mode text
    NOT NULL DEFAULT 'public'
    CHECK (sync_mode IN ('public', 'deploy_key', 'token')),
  ADD COLUMN IF NOT EXISTS deploy_key_public text,
  ADD COLUMN IF NOT EXISTS deploy_key_private_encrypted text,
  ADD COLUMN IF NOT EXISTS local_clone_path text,
  ADD COLUMN IF NOT EXISTS last_fetched_at timestamptz;

-- Backfill: rows that have a PAT are legacy 'token' mode. Everyone
-- else defaults to 'public' — the least-privileged reasonable guess.
UPDATE github_sync_configs
   SET sync_mode = 'token'
 WHERE sync_mode = 'public'
   AND token_encrypted IS NOT NULL;

COMMENT ON COLUMN github_sync_configs.sync_mode IS
  'How the clone authenticates: public (HTTPS, no auth), deploy_key (SSH), or token (legacy PAT). Token mode is deprecated for new configs.';
COMMENT ON COLUMN github_sync_configs.local_clone_path IS
  'Absolute path to the clone on disk. Null until first successful clone.';
COMMENT ON COLUMN github_sync_configs.last_fetched_at IS
  'Timestamp of the last successful git fetch. NULL if never fetched or clone failed.';
