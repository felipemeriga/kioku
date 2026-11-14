# Vault V2 Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Separate credential storage from explicitly authorized delivery recipes without widening legacy access.
**Architecture:** Add isolated credential, recipe and grant metadata tables. Reuse the existing private Infisical provider and immutable operation protocol; leave V1 binding execution intact. Device-only resolution returns bounded typed descriptors after authorization before and after provider I/O.
**Tech Stack:** Python, FastAPI, Pydantic, PostgreSQL, Infisical, cryptography.
**Spec:** /Users/feliperamosdasilva/personal_projects/kioku-vault-v2-design/docs/superpowers/specs/2026-11-14-resource-credentials-v2-design.md

## Global Constraints
- No values in metadata/MCP/DB/audit; no new local service or vault reset.
- Legacy binding IDs and grants remain independent; no inferred secret equivalence.
- Exact credential and usage revisions; grants pin usage revisions and allowed fields/capabilities.
- Raw secret argv requires explicit grant and invocation acknowledgment.

## Review Focus
- Cross-root IDs must fail before provider I/O.
- Revocation, changed recipes and expiration during provider I/O must prevent delivery.
- Uncertain provider writes must remain blocked until deterministic reconciliation.
- Legacy variants must never merge or gain another binding's fields.
- SSH key/passphrase mismatch and unsafe file paths must fail with sanitized errors.

### Task 1: Strict public contracts
**Files:** services/root_access/v2_models.py, tests/test_root_access_v2.py
**Interfaces:** CredentialInstance, Usage, UsageGrant, ResolveV2 models; typed env/argv/file/ssh descriptors.
- [x] Write negative validation tests for controls, paths, fields, SSH and raw argv.
- [x] Implement bounded discriminated models; run targeted tests.

### Task 2: Additive persistence and immutable writes
**Files:** supabase/migrations/20261114230000_root_access_v2.sql, services/root_access/v2_store.py
**Interfaces:** V2Store.catalog/create_credential/update_credential/write/reconcile/create_usage/grant.
- [x] Add service-only tables, immutable write RPCs and CAS metadata update RPCs.
- [x] Backfill one V2 legacy variant per V1 binding without unioning grants or fetching values.
- [x] Implement owner/root guarded operations; test no mapping prerequisite and sanitized metadata.

### Task 3: Resolution and management routes
**Files:** routes/root_access.py, services/root_access/v2_store.py
**Interfaces:** POST secret-access/resolve-v2, root-access credentials/usages/usage-grants routes.
- [x] Test cross-root access, revoked grants, changed revisions, conflict resolution and post-I/O rechecks.
- [x] Implement two-phase bounded resolution and descriptor construction.
- [x] Implement SSH validation/fingerprint, write HMAC and recovery.

### Task 4: Metadata discovery and release readiness
**Files:** services/root_access/discovery.py, backend/db/schema.sql
- [x] Add safe V2 metadata discovery without provider references or values.
- [x] Run V1 and V2 regression suites and formatting/lint.
- [x] Commit/push branch and open PR for parent security/CI review; no independent rollout.

## Ledger
- 2026-11-14: Isolated branch feat/vault-v2-backend from 2cdc7ec. Parent coordinates deployment and production migration. User approval covers implementation.

- 2026-11-14: 94 synthetic-only Python tests pass (54 V1 and 40 V2), ruff clean. Actual PostgreSQL16 disposable migration/compatibility/write-recovery acceptance passed; workflow now runs it continuously. Required cryptography SSH bcrypt extra added after encrypted-key test exposed missing dependency. Bound untrusted bcrypt work to 128 rounds before decrypting.
- Ruling: Legacy credential instances remain metadata-read-only and writes forward to V1, preserving existing IDs/permissions and ongoing old-client changes via triggers. Existing device grants remain independent and do not authorize newly created recipes.
- Ruling: AWS region is public per-instance metadata; optional session token may be absent on rotation, inherited token/selectors are cleared; AWS recipes restricted to atomic env pair or default credentials file, never raw argv.
- Remaining: parent review, CI and coordinated migration/release/E2E; no production changes made by this branch.

- Review follow-up: grant approval now requires reviewed usage revision and executes a row-locked CAS RPC; migrated V2 revocation also revokes its V1 permission in the same transaction. Real PostgreSQL acceptance confirms stale approvals and both protocol revocations. Defense-in-depth process-control names aligned with CLI, literal whitespace preserved, unsupported empty literal/overlong config flag rejected.
- Operational requirement: production migration must hold SHARE ROW EXCLUSIVE locks on V1 bindings/grants/resources inside the same transaction as backfill, trigger installation and registry update. Prepared dry-run-first Management API script and private loopback candidate script under /tmp; neither applies automatically.
