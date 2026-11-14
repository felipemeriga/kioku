# Central vault

Infisical0.167.10 is private on the dedicated kioku-vault-access Docker network. Clients never
connect to it directly. Kioku CLI uses the public Kioku HTTPS API. This stack
adds dedicated durable PostgreSQL and Redis volumes; it never reuses Kioku's
queue Redis or Supabase database. Do not use `down --volumes`.

## Installation

1. Copy this folder to a protected server directory, mode0700.
2. `python3 prepare.py /protected/vault-directory` creates new0600 keys and a DB password.
3. Escrow `ENCRYPTION_KEY` and `AUTH_SECRET` separately from DB backups in an
   operator-controlled secure location. Never commit/upload them as build artifacts.
4. `docker compose --env-file vault.env up -d` (create the dedicated `kioku-vault-access` network first).
5. Run `python3 bootstrap.py --directory /protected/vault-directory
   --recovery-directory /different/protected/recovery-directory`. This invokes the
   pinned provider bootstrap API inside its container, creates a new organization
   and project, and captures credentials only in0600 files. Existing checkpoints
   resume instead of creating duplicate identities. Existing completed backend env
   files are never overwritten.
6. Bootstrap creates a dedicated machine identity with organization `no-access`
   and membership only in the Kioku project (`member` role), then Universal Auth
   with300-second access tokens. Project member can manage secrets within that
   dedicated project; it is not an organization administrator. Bootstrap admin
   credentials stay solely in separate operator recovery files. Copy the resulting
   protected `backend-vault.env` into the backend deployment environment without
   printing its contents. Keep the HMAC write key stable across rolling deploys.
7. Set backend `KIOKU_VAULT_URL=http://kioku-vault:8080`,
   `KIOKU_VAULT_ALLOW_INTERNAL_HTTP=true`, `KIOKU_VAULT_PROJECT_ID`, and
   `KIOKU_VAULT_ENVIRONMENT=prod`. Internal HTTP stays on the host's private Docker
   network. Set an HTTPS vault URL instead if the provider moves off-host.
8. Apply `20261114190000_root_access.sql` through the normal DB migration path.
   Do not enable user grants until the synthetic acceptance and restore drill pass.

Existing service env vars are additive. Do not restart unrelated services or
change credentials in their compose projects.

## Backups and recovery

Install `age`; run `backup.py --recipient <public-age-recipient> --directory
<protected-backup-directory>`. This pipes pg_dump directly into encryption,
creates no plaintext dump, and sets0600 output. Schedule daily and copy encrypted
backups off-host. Keep at least7daily and4weekly copies. Never put the age private
key next to the backup directory. Recovery keys are not stored inside this vault.

Restore drill: create a separate disposable Postgres instance with no published
port; decrypt using the operator's age identity and pipe into pg_restore. Start
an isolated Infisical at exactly the pinned version with restored DB and the
escrowed original ENCRYPTION_KEY/AUTH_SECRET. Retrieve a synthetic canary via a
separate test identity; compare hashes without displaying the value. Verify
original production volumes/network are not selected before cleanup. Restoring
without the original encryption key cannot recover credential plaintext.

No automated production restore is provided: restoring changes live credential
state and requires an explicit operator decision. Backup/restore evidence must be
recorded before claiming production readiness. Catalog access remains available
when the vault is unavailable, while secret resolution fails closed.
