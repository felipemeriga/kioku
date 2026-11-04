# Deployment and recovery

## Choose the deployment surface

The root `docker-compose.yml` is a basic backend/MCP/frontend example. It does
**not** provision the complete current service topology: Redis, arq worker,
Mihari, and Tsukai are not included. Upload processing requires a worker and its
queue. Use the service definitions under `deploy/hive/kioku/` as the production
reference, with `deploy/hive/env.kioku.example` as the configuration inventory.

Frontend `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are public build-time
values. Rebuild the frontend when they change. Service keys, runner credentials,
API keys, and encryption material belong in deployment secrets.

## Release workflow

`.github/workflows/ci.yml` invokes the shared checks. The release workflow runs
following successful main CI when `KIOKU_RELEASE_ENABLED=true`. The scripts under
`scripts/release/` plan affected versions, build/publish images, coordinate Dokploy
updates, and verify deployment/image state. Native CLI packaging is in
`.github/workflows/cli-native.yml`. Review the actual workflow and environment
example for required GitHub variables and secrets before enabling release.

Migrations are a separate operational responsibility. Apply required ordered SQL
changes as the migration owner before code that depends on them. Neither a merged
PR nor a published image proves that a migration was applied or a feature enabled.
Do not apply `backend/db/local_setup.sql` to production.

## Tsukai rollout

1. Apply the Tsukai execution and follow-up migrations in order. Use
   `supabase/migrations/20261104*.sql` and the runtime grant template as the
   authoritative dependency list; include domain-side bridge/receipt migrations.
2. Provision a dedicated PostgreSQL login with `NOSUPERUSER NOBYPASSRLS NOINHERIT`
   and no role memberships. Run `tsukai/ops/grant-runtime.sql` as migration owner
   with `runtime_role` set to that login. Reapply the idempotent template after
   schema upgrades. Never use the Supabase service role as the runner DB login.
3. Configure separate service and capability secrets, explicit entitled owner IDs,
   native credentials, persistent native state/workspaces, and database TLS trust.
   Use the checked-in Tsukai Compose definition for mounts and restrictions.
4. Start one runner replica and check `/health/live` and `/health/ready` privately.
   Readiness checks cached authentication and database state; health polling must
   not repeatedly invoke inference. `/internal/recheck-auth` performs the explicit
   recheck after credential rotation.
5. Configure backend **and worker** with matching runner URL, transport/capability
   credentials, credential owner, and operation allowlist. Enable only verified
   operations through `TSUKAI_NATIVE_TASKS`. Mihari native routing has its separate
   `TSUKAI_MIHARI_NATIVE` gate.
6. Verify scoped chat, replay, cancellation, recovery, usage, and maintenance
   publication in an integration environment before enabling ordinary traffic.

The runner uses a direct PostgreSQL/session-mode connection; transaction pooling
is unsupported. Configure verified TLS and the mounted public CA as documented in
[the protocol](../tsukai/protocol/README.md). Keep native credentials in native
state/environment, outside logs and source control.

Drain the old runner with authenticated `POST /internal/drain`, then stop it before
replacement. Persistent state does not make concurrent replicas safe. A disconnect
is not cancellation; use product cancellation routes. Uncertain sessions need an
explicit rebuild/retry from committed history, never reuse of the uncertain turn.

Subscription list-equivalent USD is an accounting estimate, not a cash charge or
proof of a hard spending cap. Unknown counters remain unknown.

## Mihari

The poller retains repository state under `MIHARI_DATA`, decrypts git credentials,
and indexes through authenticated backend APIs. Preserve its data mount and KMS
configuration across replacements. Do not run old watcher and new Mihari schedulers
against the same registrations concurrently. `/api/watcher` compatibility and
legacy environment handling support rolling upgrades; current configuration uses
`MIHARI_*`. See [Mihari](../mihari/README.md).

For native maintenance, Mihari gets a backend-prepared request and submits directly
to Tsukai. Canonical publication and acknowledgement are separate steps: a completed
runner job is not by itself proof that a briefing/document/learning was published.

## Triage

| Symptom | First checks |
| --- | --- |
| Upload remains queued | Redis connectivity, worker process, ingestion job error |
| CLI reaches wrong server | `KIOKU_API_BASE`, persisted config, `--api-base` precedence |
| Native models unavailable/stale | Runner readiness/auth, catalog refresh, owner entitlement |
| Native chat interrupted | Durable turn/job state and replay; explicit retry if uncertain |
| Machine offline | Manabi login service and `kioku status`; sleeping hosts cannot connect |
| Maintenance finished but UI stale | Publication receipt/ack and current source revision |

Deletion is asynchronous across product and native state. A `202` response means
accepted/pending, not completed erasure. Check the deletion state until cleaned.

## Unmerged rollout work

Original-agent evidence in [PR #214](https://github.com/felipemeriga/kioku/pull/214)
has its own migration, opt-in flag, and outstanding real Storage/PostgREST
integration gate. Do not apply its rollout instructions as if they were main's
current deployment requirements. See [change status](change-status.md).
