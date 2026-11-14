# Root access backend implementation plan

> For agentic workers: execute using Superpowers executing-plans, with a final independent review.

Goal: centralized Infisical credentials with root-scoped metadata and separately enrolled device access.
Architecture: existing FastAPI/Supabase metadata, service-only transactional RPCs for enrollment and secret-write CAS, isolated durable Infisical Compose. No plaintext in metadata or MCP.
Spec: ../specs/2026-11-14-central-vault-design.md in approved vault-spec worktree.

## Global constraints

- Single-owner roots, explicit device grants, HTTPS for CLI, no local daemon, no secret reveal API for JWT/MCP.
- Secret 64KiB per field/256KiB total/32 fields; guide64KiB; names120; aliases20x120.
- Multi-binding1–8, no duplicate env destinations, no cross-root access, no fallback on provider failure.

## Review focus

- Enrollment polls racing cannot both receive credentials.
- Secret writes racing cannot publish against the wrong binding revision.
- Secret validation failures cannot echo input through FastAPI422 or logs.
- Provider outage cannot break ordinary metadata/chat reads.
- Root moves, revoked grants/devices and expired bundles deny retrieval.

## Tasks

1. Schema and contracts: add root access metadata tables + service-only atomic RPCs. Test model bounds/unsafe env variables and owner/root checks. Commit.
2. Provider adapter: Infisical Universal Auth and immutable JSON secret bundle reference per write operation, no exposed values/errors; test TLS/origin config, API bodies and failures. Commit.
3. Catalog/management routes: aggregate + guides/environments/resources/bindings/write-only credentials + transactional CAS. Test no-value serialization, unknown fields, cross-root relationships, input-value error suppression/idempotency. Commit.
4. Enrollment/grants/resolve: hashed device credentials, browser approval, atomic consume, exact grants/revisions, no-store multi-binding result; test invalid credentials, revocation, expiry, wrong root, duplicates and partial failure. Commit.
5. Durable deployment: isolated pinned Infisical/Postgres/Redis compose, backup/restore scripts and bootstrap instructions; validate Compose and synthetic restart persistence. Coordinate root before live provisioning/migrations.
6. Focused tests + lint, independent root review, PR; no auto-merge.
