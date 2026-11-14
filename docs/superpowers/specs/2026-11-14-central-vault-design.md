# Centralized secrets and environment context

Date: 2026-11-14
Status: Proposed design for approval; no product implementation authorized by this document.

## Intent

Let coding agents on several computers use the correct company resource during any point of a session without the user copying credentials. One session may test staging, query shared Grafana, then inspect another AWS account. Environment belongs to each operation, never to the lifetime of a session.

Kioku owns the human-readable environment guide, resource catalog, authorization and user experience. A central secrets provider owns secret values. The existing CLI performs short-lived authenticated HTTPS requests and local execution. No local daemon, replicated vault, Orca fork, or new execution server is required.

## Decisions and alternatives

User requirements: central deployment only; on-demand access; root-folder organization; Markdown describing company-specific environments and shared tools; semantic discovery despite different variable names; avoid secrets in MCP, prompts, journals and Originals.

Proposed provider: Infisical self-hosted, behind the existing deployment infrastructure. Its documented machine identities and API enable a server adapter. This provider choice is a recommendation, not a previously approved implementation decision. Verify the pinned release, licensing and availability of required permission/audit features before implementation; do not silently substitute paid functionality.

Alternatives: OpenBao supports centralized secret storage and process injection but introduces different operational/unseal requirements. A custom encrypted database reduces infrastructure but makes Kioku responsible for vault cryptography and recovery; rejected for initial scope. Per-computer vaults/daemons rejected by the user because of synchronization and operational failure points.

Integrate via a narrow server-side provider interface, not a provider SDK scattered through routes. Do not build a generic plugin framework. Initial deployment has exactly one configured provider. Provider credentials never reach clients.

## Verified integration points

Current CLI `cli/src/lib/config.ts` persists user access/refresh tokens in a mode-0600 config, with configurable API URL. `backend/auth.py` validates Supabase JWTs. `backend/routes/api_keys.py` manages independently revocable, folder-scoped MCP keys; those keys are readable by agent tooling and MUST NOT automatically gain secret retrieval rights. Folder access validation already exists in `services.scope`.

These observations are integration anchors, not claims that secrets or device enrollment already exist. Implementation must recheck current main and schema.

## Trust boundaries and guarantees

HTTPS with certificate verification protects transport. Provider encrypts stored values; backups and encryption-root recovery need a separate protected backup. Plaintext necessarily exists in server, CLI and child-process memory during use. Ordinary Node/Python memory cannot guarantee secure zeroization.

Guarantee: discovery/MCP results never contain secret values, and normal execution does not place values in command arguments, environment-guide text, persistent Kioku storage, model requests or recorded result bodies.

Non-guarantee: an arbitrary child process can print, encode, persist or transmit injected values. An agent with unrestricted terminal access under the same OS identity can deliberately extract credentials. Redaction is defense in depth, not a sandbox or proof that transcripts cannot leak. Do not market this as agent-blind secret use. Stronger agent-blind access requires constrained server-side connectors or OS isolation and is outside the initial arbitrary-command feature.

Compromised backend or client can access the secrets granted to it. Users only register credentials they are authorized to use; company policies can prohibit replication in this vault. No broad production authorization is inferred from root membership.

## Product experience

Root-folder Settings gains Environments & Access:

- Guide: sanitized Markdown, revision history, no raw HTML execution; warns that this is contextual documentation, not a secret-entry field.
- Environments: explicit IDs and names, e.g. development, staging, production. No assumed universal set or silent default.
- Resources: name, description, aliases, service/account/region metadata, shared or environment-specific availability, and reference bindings.
- Access: enrolled computers, resource/environment grants, expiration and revoke actions.
- Activity: access metadata without values, commands, query bodies or output.

Example: one Grafana resource shared by all environments, three MongoDB SES bindings, separate MongoDB business-api bindings, and AWS accounts/roles. Shared Grafana credentials do not remove the need to choose the target environment in a query.

Creating/replacing a secret uses a dedicated password/multiline/file field and dedicated endpoint. Values are never put into Markdown, URLs, localStorage, autosaved drafts, analytics or client error reports. No plaintext reveal/export button in the initial release. Replacement is explicit; existing values cannot be fetched by the editor.

Preview the mapping before save: `SES MongoDB / staging -> resource UUID / secret fields -> MONGO_URI`. Never show values in preview. Inline, accessible validation messages use the established UI styles. Ambiguous selections and missing grants are actionable errors, not empty states.

## Catalog and deterministic resolution

Natural-language discovery searches only authorized guide/catalog metadata. Start with names, descriptions, aliases and existing metadata search; no new embedding dependency. An agent can reason over returned metadata. Secret values are excluded from all indexes.

Discovery yields candidate IDs, environment/account/region and available bindings. More than one valid candidate requires explicit selection. Execution requires exact immutable resource and binding IDs, explicit environment when applicable, and a catalog revision. Never execute directly from fuzzy text. Revalidate authorization and binding revision at retrieval; return conflict if mapping changed.

Resource aliases help find “banco de homologação do SES.” Explicit bindings map the same secret to `MONGO_URI`, `MONGODB_URL` or another crate-specific variable. Repository/consumer profiles select these mappings; they do not grant access. Root membership is verified server-side on every request, including descendants and moves. Moving a folder never silently transfers vault ownership or grants.

## Proposed data model

All metadata rows carry owner/tenant identity, timestamps, IDs and revision. Initial authorization is single-owner with per-device grants; multi-user company sharing is deferred, not approximated by folder names.

- `root_access_guides`: root_folder_id, Markdown, revision.
- `root_environments`: root_folder_id, slug, display name, sensitivity.
- `access_resources`: root_folder_id, name, aliases, description, type, shared flag, nonsecret account/region metadata.
- `access_bindings`: resource_id, optional environment_id, consumer profile, provider reference, opaque field mapping, revision, enabled. Provider references are server-only.
- `secret_devices`: owner_id, label, credential hash, created/last_used/revoked timestamps. Possession establishes an enrolled client, not hardware attestation.
- `secret_grants`: device_id, binding_id, allowed operation (`exec`), expiry, revoked_at. Metadata discovery has separate folder-scoped permission.
- `secret_access_events`: request_id, owner/device/root/resource/binding IDs, action, binding revision, timestamp, outcome and safe error code. No values or arbitrary request payload.
- `secret_write_operations`: idempotency key, opaque provider path/reference, state, metadata revision; no plaintext payload. Supports crash reconciliation across DB/provider writes.

RLS and explicit owner/root filters are both required because service-role access can bypass RLS. Do not put ciphertext copies in Kioku tables as a fallback vault.

## Authentication and authorization

Interactive UI uses existing user JWT plus root ownership for management. Enroll a device through a short-lived, one-time browser-approved flow: CLI creates an enrollment request, browser shows device/root and requested privileges, user approves, CLI receives a new device credential once. User login alone and existing MCP API keys cannot retrieve values.

Device credential is independent from global CLI JWT and repo `.mcp.json`; prefer OS credential storage, with an explicit mode-0600 fallback if unavailable. No dependency on a resident agent. Credentials never appear in enrollment URLs, process arguments or logs. Polling possession token is separate from the browser approval identifier. Expired/consumed approvals cannot be reused. Initial device credential lifetime: 30 days; re-enrollment required, per-device revocation supported. Exact keystore library is an implementation choice.

Every retrieval checks device active state and exact binding grant, including production. Explicit production grants are set in UI, so authorized automated use does not require a prompt on every command. Revoke prevents subsequent retrieval; it cannot erase a static password already delivered to a running process. Provider rotation/revocation is required for that. No shared all-roots machine master credential.

## Proposed interfaces

Names below are design contracts, not existing tools.

MCP `discover_access_resources(query, environment?, account?)`: folder-scoped metadata only. No read-secret tool. `get_environment_guide` exposes authorized Markdown and revision. Tool schema excludes credential-value fields and provider paths.

Management APIs under `/api/root-access/{root_id}` manage guides, environments, resources, bindings, enrollment approvals and grants using JWT authorization. Secret create/replace uses a separate write-only route. List/read returns only presence/version metadata, never masked values that reveal prefixes/suffixes.

`POST /api/secret-access/resolve`: device authentication, one to eight exact binding IDs/revisions and invocation UUID; authorize every binding and return one combined response only after all reads succeed; returns field values for the authorized binding over HTTPS, `Cache-Control: no-store`, no redirects. This endpoint is reachable by CLI but is not exposed as MCP. The transport itself is not a security boundary: permissions enforce separation.

No retries of successful resolution/execution just because a response or child process fails. Bounded retry of pre-delivery transient reads is acceptable under the same invocation ID and reauthorization, logged as attempts. Never retry the child command automatically.

## CLI execution

Proposed usage:

```sh
kioku access list --root cosm
kioku exec --binding <binding-uuid> --revision 4 -- cargo test -p ses-ingester
```

Multiple resources are supported in v1 through repeatable `--binding UUID@revision` arguments (the single-binding example above also permits a separate `--revision`). A command needing MongoDB and AWS selects both explicitly. Resolve all bindings before starting any process; deny partial access/results if any grant or read fails. Duplicate variable names across bindings are rejected even if values happen to match. Each binding retains its own explicit environment/account. Do not manufacture composite resources to evade authorization.

Each call fetches fresh authorized values and spawns the child directly as argv, without implicit shell evaluation. CLI resolves root from the repository binding or an explicit authorized root; never trusts CWD alone as authorization. No `secret get`, `export`, `--print`, permanent `.env` generation or shell-global injection in v1.

Environment names must match `[A-Za-z_][A-Za-z0-9_]*`, with length bounds and an allowlist from the saved consumer profile. Block dangerous loader/runtime-control variables by default (e.g. `LD_PRELOAD`, `DYLD_*`, `NODE_OPTIONS`, shell startup hooks). Overriding an existing target variable requires an explicit policy in the profile; never inherit a conflicting production connection silently. Each approved consumer profile also defines nonsecret `clear_env` names for known alternate credential selectors and aliases for its service. Before injection, remove these names, including AWS credential/profile/config-file selectors for an AWS profile and all known MongoDB connection aliases for a MongoDB profile. Validate `clear_env` with the same name and count bounds as mappings. Reject profiles with unresolved credential inheritance; staging must not silently fall back to an inherited production selector. For resources supporting SDK default chains, the profile must explicitly control credential/config files and instance-metadata fallback or be marked unsupported until a tested isolation recipe exists. Keep unrelated build variables such as PATH and compiler settings. This is deterministic profile-based isolation, not a promise to discover arbitrary hardcoded application credentials.

Resolve before spawning, enforce deadlines and payload limits, set secret variables only on the child, forward termination signals, terminate the child process group on cancellation and preserve normal exit codes. Do not persist secrets or response caches. Concurrency keeps per-invocation environments separate. No global “current environment.”

Initial support: UTF-8 scalar and multiline environment-variable values, including JSON values, within documented bounds. NUL-containing/binary secret files are rejected; temporary credential files and arbitrary file downloads are a later explicit feature. AWS v1 can inject already-valid temporary credential bundles including expiration; role assumption, refresh during long commands and dynamic secret issuance are deferred. Reject expired/near-expiry bundles rather than pretending they remain valid indefinitely.

## Output and Originals boundary

All captured child stdout/stderr goes through CLI filtering before forwarding. Implement streaming-safe matching across chunk boundaries, bounded buffers, and common escaped/URL-encoded representations of known values. Do not depend on word boundaries. Secret-bearing output cannot be written to a debug log before filtering. Noninteractive pipes only in v1; reject PTY/interactive mode until filtering is verified. Block shell tracing in wrapper-owned commands; never log the child environment.

Filtering cannot cover arbitrary transformations or secrets written directly to files. A process can bypass stdout/stderr via other channels. Therefore no absolute no-leak guarantee for arbitrary code. Prefer dedicated connectors for stronger isolation later.

Originals ingest must not assume wrapper filtering is infallible. Secret setup requests and response bodies are structurally excluded from logging, tracing, crash reports, journal generation, indexed documents and native execution preparation. Synthetic-secret canaries verify the entire capture pipeline. If a secret is accidentally pasted into chat, treat it as exposed and rotate it; do not claim deleting visible text removed immutable archived evidence/backups.

## Provider consistency and operations

Backend accesses only configured vault origin, with TLS verification, fixed timeout and least-privilege service identity. Client cannot supply a URL or provider path; prevent SSRF. Pin provider references to owner/root namespace; no user-controlled cross-namespace paths.

Create: reserve write-operation metadata, write provider value under deterministic opaque path, finalize binding reference, then mark complete. Failures never return values. Reconcile incomplete operations by opaque operation ID/provider metadata; retry with same idempotency key, not duplicate secret creation. Replacement uses provider versioning and optimistic concurrency where supported; freeze the binding while outcome is uncertain. No distributed transaction is assumed.

Vault unavailable: discovery/guide remain usable; retrieval fails closed with a styled safe error, no stale-secret fallback. No new Redis/cache/queue dependency for ordinary retrieval. Reuse backend health/metrics and existing deployment conventions. Back up provider data and required encryption material separately and test restore before production use. Provider failure must not fail chat, indexing or normal History endpoints.

## Validation and errors

Server rejects unknown fields and invalid UUIDs; validates root ownership, environment/resource relationships, enums, bounded strings (name 120, aliases 20 x 120, guide 64 KiB), secret input 64 KiB per field / 256 KiB total, maximum 32 fields, valid env names and revision integers. These are proposed v1 bounds and must match UI and CLI. No validation echoes submitted secret values. Markdown remains untrusted context, never authorization policy or executable instructions.

Use stable safe codes: `authentication_required`, `device_revoked`, `access_denied`, `ambiguous_resource`, `binding_changed`, `secret_unavailable`, `credential_expired`, `provider_unavailable`, `invalid_input`. Cross-tenant lookups do not disclose existence. Requests have correlation IDs; user-facing errors include no provider response bodies, request headers, values or stack traces.

## Acceptance and reliability gates

1. Two computers access the same authorized staging resource; revoking one blocks only its future retrievals.
2. A single session switches staging/production/shared Grafana with exact binding selection and isolated concurrent commands.
3. Same credential maps to distinct approved env variable names for two crates; ambiguity never executes.
4. MCP keys, another owner, wrong root, moved folders, revoked device, expired grant and stale binding revision cannot retrieve secrets.
5. Synthetic secret canaries do not appear in management logs, tracing, analytics, MCP, transcripts, journals or Originals during normal supported flows. Test stdout/stderr chunk splits, multiline, escaped and URL-encoded values; explicitly demonstrate residual limits against deliberate encoding/exfiltration.
6. Child failure/cancellation never causes automatic reexecution. Provider outage, TLS failure, timeout, oversized input and crash-between-provider/DB-write leave safe recoverable state.
7. UI validation/error behavior and accessible forms tested in isolated browser; CLI execution tested on two machines. Report API evidence separately from browser acceptance.
8. No secret value persists in CLI config, repository, generated instructions or index; existing chat/retrieval latency path unchanged.
9. Backup/restore drill succeeds; production remains disabled until explicit grants and provider recovery configuration are ready.

## Builder review

Independent review identified two material gaps: inherited alternate credentials could defeat environment selection, and tests can need several resources. Resolved above with service-specific credential cleanup/default-chain control and bounded multi-binding resolution before process launch. These are proposed architectural calls for approval.

## Delivery sequence

After design approval, produce an implementation plan. Implement provider adapter/management/schema and no-value catalog first, then device enrollment/grants, then CLI execution/filtering, then MCP discovery and AGENTS/CLAUDE guidance, then full canary/security and multi-machine acceptance. Start with one root and staging MongoDB; add production only after acceptance. Do not bundle Orca ticket orchestration into this work.

## Official references

- https://infisical.com/docs/self-hosting/overview
- https://infisical.com/docs/documentation/platform/identities/machine-identities
- https://openbao.org/docs/agent-and-proxy/agent/
- https://openbao.org/docs/agent-and-proxy/agent/process-supervisor/

Provider API details and feature licensing require verification against the version selected for implementation. Proposed Kioku interfaces in this document are not provider API claims.
