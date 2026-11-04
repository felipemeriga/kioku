# Agent journals, learnings, and original evidence

## Available on main

`kioku init` installs Claude Code or Codex hooks. SessionStart fetches repository
context. Stop launches a detached summarizer that appends free-topic Markdown
entries to `.kioku/memory/YYYY-MM-DD.md`. Capture and upload are asynchronous;
`kioku memory-sync` retries local daily files after network failures.

Daily files sync through the scoped Kioku key into private Supabase Storage with
repository/user/date, revision, and checksum metadata. They are not embedded into
the document search corpus. The Learnings tab exposes journal days and source-linked
learnings. Mihari can consolidate learnings with source-day and commit evidence;
“On main” does not claim that a change is deployed.

Manabi is a separate presence/inventory service. Its current inventory connection
does not crawl transcripts or continuously collect agent sessions. Do not infer
continuous memory capture merely because the machine appears online.

Implementation references: `cli/src/commands/memory.ts`, `backend/routes/learnings.py`,
`frontend/src/components/`, and the journal/learnings migrations under
`supabase/migrations/`.

## Open original-evidence work

[PR #213](https://github.com/felipemeriga/kioku/pull/213) specifies durable originals
and provides an illustrative viewer prototype.
[PR #214](https://github.com/felipemeriga/kioku/pull/214) implements that design on
its branch. Neither is merged in the snapshot documented here.

The implementation proposal preserves the existing journal summarizer and adds
immutable original-record segments/attachments, a current manifest, deterministic
upload workers, and a shared drawer/full-page reader with raw records and explicit
gaps. It does not add semantic recall. Its stated rollout requires
`20261105090000_agent_evidence.sql`, backend/worker and CLI deployment, and explicit
`AGENT_EVIDENCE_ENABLED` enablement (default false). Real Supabase Storage/PostgREST
end-to-end verification remains a gate in the PR description. Individual originals
over 64 MiB remain local with an explicit size-limit gap.

These details describe the open PR, not a configuration supported by main today.
Review the latest PR before rollout; this page is not a substitute for its final
migration and acceptance instructions.

## Design history

The continuous-memory design under `docs/superpowers/specs/` proposes a broader
Manabi/Mihari memory lifecycle. It is design evidence, not proof of a shipped
collector, memory judge, semantic recall, or Living Summary. Preserve its original
requirements while using this guide for current behavior.

See [change status](change-status.md) for the reviewed PR snapshot and
[CLI storage](../cli/README.md#files-and-credentials) for local credential boundaries.
