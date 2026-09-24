-- Allow multiple api keys per (user, scope_folder_id).
--
-- The CLI mints one ROOT-scoped key per MACHINE (each computer keeps its own
-- local key store). A second machine setting up the same repos must NOT revoke
-- the first machine's key — but the unique constraint forced create_api_key to
-- delete the prior same-scope key on every mint, so two machines fought over
-- one key. Dropping the constraint lets each machine hold its own root key;
-- keys are independent (looked up by key_hash) and revocable from the UI.

ALTER TABLE "public"."api_keys"
    DROP CONSTRAINT IF EXISTS "api_keys_user_scope_unique";
