# Vault CLI Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enroll a separately authorized computer and execute local commands with scoped central-vault credentials without a daemon.
**Architecture:** Existing CLI communicates directly with backend via HTTPS. Metadata discovery uses user auth; secret resolution uses separately enrolled device auth. Child argv is spawned without shell, with isolated env and filtered pipe output.
**Tech Stack:** TypeScript, Node >=18, Commander, native fetch/streams/child_process; no new runtime dependencies.
**Spec:** docs/superpowers/specs/2026-11-14-central-vault-design.md in docs/central-vault-spec branch.

## Global constraints

No secret-value output/export; no command retries; exact binding UUID/revision; 1–8 bindings, <=32 env fields and bounded values; no plaintext provider logs. No local daemon or permanent .env. Separate mode0600 device credential store, explicit fallback disclosed. HTTPS only except explicit loopback development.

## Review focus

- Secrets split across arbitrary stdout chunks including UTF-8/escaped representation must remain filtered.
- Inherited AWS/profile/loader selectors must not override injected staging credentials.
- Invalid mapping, duplicate binding, expired credentials must prevent spawn.
- Network/provider/child failure must never reveal error bodies/secrets or execute twice.
- Concurrent execution and termination must not mutate parent env or leave child group running.

### Task 1: Execution core
Files: cli/src/lib/secret-exec.ts, secret-exec.test.ts.
Interfaces: createSecretRedactor(values:string[]):Transform; buildSecretEnvironment(parent, values, clear):ProcessEnv; runSecretCommand(argv:string[], resolved:ResolvedAccess):Promise<number>.
- [ ] Add failing tests chunk boundaries, JSON/URI escape values, dangerous env names, inherited alias cleanup, duplicate name constraints and exit code.
- [ ] Implement bounded stream redaction before output, shell:false child process group and cancellation.
- [ ] Run npm run build and node --test dist/lib/secret-exec.test.js; expect all pass.
- [ ] Commit execution core.

### Task 2: Device API and storage
Files: cli/src/lib/secret-access.ts, secret-access.test.ts.
Interfaces: request enrollment/poll, metadata GET, resolve POST, explicit per-root per-API device store. Consume backend contract shared by vault_backend_infra.
- [ ] Add failing tests non-HTTPS, redirects, missing/expired device, response limits, token permission and endpoint binding.
- [ ] Implement abort deadlines/body bounds, safe fixed errors, no values in errors; atomic0600 fallback store and no secret-response caching.
- [ ] Run build and tests; commit API/storage.

### Task 3: Commands and memory instructions
Files: cli/src/commands/access.ts, cli/src/index.ts, relevant generated instructions template after inspecting current source.
- [ ] Test enroll/list/forget and repeatable binding parser; malformed input never requests secrets.
- [ ] Add access enroll/list/forget plus exec --root UUID --binding UUID@revision -- command argv.
- [ ] Use device enroll explicit user approval; never print polling secret/token.
- [ ] Add metadata-only MCP discovery instruction reference after server tool implemented; no secret retrieval MCP.
- [ ] Full CLI tests/lint/format; commit/push PR; independent review and real backend integration before merge/deploy.
