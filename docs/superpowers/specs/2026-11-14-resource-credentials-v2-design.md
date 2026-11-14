# Resource credentials and usage — V2 design proposal

Date: 2026-11-14
Status: Draft for visual and architectural review. This document and its HTML are not product implementation or migration authorization.
Prototype: `design-system/prototypes/root-access-v2.html`.

## Problem and intent

V1 places the secret on an application binding. The person must first choose an environment, consumer and variable mapping before the Add credential action appears. This mixes “what access do I have?” with “how does this application consume it?” and can duplicate the same credential across consumers.

The user wants different companies’ conventions: one shared Grafana, three MongoDB environments, SSH keys, an argument to a CLI, or a key in a configuration file. A Markdown guide should explain those conventions to the agent. The vault stays centralized; the CLI remains an on-demand client, with no persistent service on each computer.

## Design direction

Retain Kioku’s existing palette: background `#090710`, panel `#120b20`, divider `#392747`, primary magenta `#ff079e`, active cyan `#24dfef`, success `#73dab0`. Use the established system font and monospace only for identifiers, paths and command previews. No new branding or decorative cards. Content is left aligned and top anchored; changing tabs must not move the heading. The user rejected the explanatory right column, so the catalog uses the full content width.

The memorable interaction is direct access to each environment’s credential from the catalog. No resource-side marketing/tutorial panels and no mandatory mapping wizard.

## Approaches considered

1. Add more delivery types to V1 bindings. Smallest code change, but keeps secret storage attached to every application and retains the confusing per-environment UX.
2. Separate credentials from usage recipes. A resource/environment owns one credential bundle; several applications describe how to consume it. Recommended because it fixes the underlying coupling and supports different company structures.
3. A free-form Markdown-only execution recipe. Flexible, but mixes untrusted instructions with authorization and cannot enforce deterministic injection or cleanup. Markdown remains context, never an execution policy.

Option 2 is the proposal shown in the HTML, not an approved backend migration yet.

## Product model

- **Resource:** the system or access being described, its credential schema and discovery aliases. Examples: SES MongoDB, Grafana, Deployment host.
- **Availability:** selected company-defined environments **or Shared**. Shared is a first-class availability option; it means one credential rather than copies for every environment.
- **Credential instance:** one resource plus one environment (or Shared), opaque vault reference, version, optional expiration and write/recovery state. It exists without an application mapping.
- **Usage recipe:** application/repository, purpose, referenced credential fields, delivery instructions and immutable revision. It never stores another copy of the values.
- **Guide:** company Markdown explaining which resource/environment/recipe applies. Natural-language reasoning selects candidates; execution requires exact IDs and revisions.

Account and region are optional additional metadata, shown only when useful. A generic resource is not forced into an AWS account/region structure. Credential schema changes after storage need explicit versioned migration; changing availability must never silently clone a Shared secret into Production.

## Primary flows

### Add or replace a credential

Catalog rows show environment badges, including Missing/Stored state. Clicking “Staging +” opens the dedicated Staging credential form directly. The resource drawer’s Credentials tab repeats the same rows with explicit Add credential/Replace actions. There is no consumer name or variable mapping on this path.

Connection URI, API key, SSH key and Custom fields use dedicated forms. Values are write-only; a stored value cannot be revealed. Expiration and non-secret notes are secondary details. Never place a secret in the Markdown guide, a URL, autosave, localStorage, a model call or an analytics payload.

### Add a usage

Separate How to use tab: name the application/purpose, choose the delivery, select source fields and enter destinations. Examples:

- `credential.connection` → `MONGO_URI` for SES ingester.
- The **same** `credential.connection` → JSON Pointer `/database/uri` in a temporary config for Business API.
- Temporary config path → `--config` for a diagnostic CLI.
- `credential.private_key` → temporary SSH identity file for a pinned host.

A credential can be stored before any usage exists. A usage can be drafted before values are present, but execution is unavailable until all required fields and grants exist.

### SSH

Store a private key and optional passphrase centrally; keep a public fingerprint/label as non-secret metadata after validation. A recipe includes host, user, port and a verified host-key fingerprint obtained through a trusted channel. No automatic host acceptance or `StrictHostKeyChecking=no`.

The CLI materializes a unique protected identity file per invocation (`0700` directory, `0600` file), or uses a short-lived invocation-scoped helper where needed for passphrases. It terminates that helper and cleans files on normal exit/cancellation. No resident daemon or replicated local vault. Encrypted key handling must be proven with noninteractive tests; never quietly ignore the passphrase field.

A hard kill or machine crash can prevent immediate cleanup. Any implementation must use an owned manifest with expiration and safe stale-file cleanup on the next CLI invocation, without following symlinks or deleting unrelated files. Disk blocks cannot be promised securely erased. This is an explicit expansion of V1’s no-secret-files boundary, not an invisible change.

### Command arguments

Distinguish **non-secret values**, **temporary file paths**, and **raw secret values**. Prefer a file path, stdin or environment variable where the application supports it. A file path in `--config` is not the secret.

If a legacy tool requires a raw secret in argv, the recipe must explicitly declare that capability, display the process-list exposure and require acknowledgement. The server/device grant must authorize that capability separately. Such a recipe cannot claim “the value never enters arguments.” Output filtering does not conceal process arguments, tool tracing or crash reports. No implicit shell or string concatenation; execute argv arrays.

### Configuration files

Initial proposed formats: JSON, YAML and TOML with a typed key path. Read a bounded approved non-secret template and create a temporary copy. Use a safe parser/serializer; never eval templates or language expressions. A recipe must also say how the application finds the file (argument, non-secret environment path, or an explicitly supported isolated working-directory mode).

The original repository file is not overwritten. Temporary files have restrictive permissions, are outside the repository and are cleaned with the invocation. Reject traversal, untrusted symlinks, duplicate/conflicting destinations, unsupported encodings and ambiguous key paths. JSON uses JSON Pointer; YAML/TOML need a documented escaped-segment path representation before implementation. Arbitrary binary formats and arbitrary in-place edits are not implied by “config file.”

## Authorization and execution

Root ownership and enrolled-device authorization remain independent of discovery and prose. Metadata-only MCP never returns values, provider paths or device credentials. One operation explicitly chooses resource credential ID/version, environment/account and usage ID/version. There is no session-global active environment and no silent Production fallback.

Credential authorization must include allowed fields. Recipe execution also needs approved delivery capabilities and relevant destination constraints. New fields, raw-argv delivery, new SSH hosts, broader file destinations or broader environment/account scope cannot be gained by simply editing a recipe. Ordinary display-copy edits do not require new secret access, but semantic changes increment the recipe revision.

Multi-resource execution authorizes and resolves everything before spawning once. Reject conflicting environment destinations, argv ownership and file paths; do not partially execute. Continue V1’s safe failure, no automatic command retry, revocation checks after provider I/O, expiry margin, stream-safe redaction and process-group cleanup.

A grant cannot erase a secret already delivered to a process. Arbitrary code with the same OS identity can deliberately expose injected values. V2 does not turn the CLI into a sandbox or make secrets invisible to a fully privileged local agent.

## Additive persistence and V1 compatibility

Suggested new metadata units (exact names are proposals): `resource_credential_instances`, `resource_usage_recipes` and narrowly scoped credential/recipe grant associations. Secret values remain only in the provider. References, field schemas, versions and recovery IDs remain server-owned; plaintext never enters Kioku’s tables.

Migrate each V1 binding to a credential instance plus a **legacy environment-variable recipe**, preserving its provider reference, expiration, field exposure and exact existing device grants. Existing `kioku exec --binding UUID@revision` continues through a compatibility resolver until a documented deprecation, rather than breaking installed clients.

Do not automatically merge different V1 bindings just because resource/environment names match. They can hold different values or expose different fields. First preserve them as explicit legacy variants. Deduplication can be offered only when opaque references are identical, or privileged provider-side comparison proves canonical bundles equal without returning values. Different values need user selection; do not pick the newest by assumption.

Grant migration is conservative: an old grant for binding A maps only to A’s allowed fields and legacy recipe/capabilities, not all fields or all recipes associated with a newly combined credential. Never union grants into broader access. An operator-approved canonicalization can later consolidate instances after previewing the effect. Rollback keeps old bindings resolvable until the migration is accepted.

Retain immutable write operations and reconciliation: if a provider write succeeds but metadata commit is uncertain, recovery can finalize the original operation without asking the user to resend plaintext. If absence is confirmed, CAS cancellation permits a fresh attempt; uncertainty remains blocked and actionable.

## Prototype scope

The HTML is disconnected, uses illustrative metadata and discards entered values. It does not validate real SSH keys, connect to hosts, execute commands, edit files, create grants or write to the provider. Nothing is sent to a network endpoint or persisted in browser storage. Reload resets all demonstration state.

Demonstrated interactions: direct environment credential entry/replacement; Shared resource without account/region; safe guide preview; resource creation; environment creation; separate env/argv/file/SSH recipe forms; explicit raw-argv warning/acknowledgement; host fingerprint requirement; input errors and keyboard dismissal.

## Implementation acceptance before any V2 release

- Direct credential creation requires no recipe and stores one instance per selected environment.
- Two usage recipes share one instance; rotation updates both without copying the secret.
- Shared resources have one credential and never demand account/region.
- Existing V1 CLI and grants still work; migration never expands fields, environments or delivery capabilities.
- SSH key plus passphrase, known-host mismatch and noninteractive connection failure behave safely; cleanup after success/cancel/crash is tested.
- JSON/YAML/TOML escaping, symlink/traversal rejection and temporary-copy cleanup are tested; original tracked files remain byte-identical.
- Raw argv is denied without explicit policy; exact argv and all observability limits are documented honestly.
- Credential canaries do not appear in MCP, journals, Originals, response/error logs or successful output through supported paths.
- Header/tabs remain at fixed top positions across short/long tabs, and no document/drawer overflow at 390, 720, 1024 and 1512 pixels.

No V2 runtime/backend changes or production migration are included in this proposal.

## Reference checks

The SSH proposal is grounded in the official OpenSSH interface for identity files and host-key checking. Passphrase support needs an explicit noninteractive implementation and test; it is not assumed to happen automatically.

- https://man.openbsd.org/ssh.1
- https://man.openbsd.org/ssh_config.5
- https://man.openbsd.org/ssh-add.1
