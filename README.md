# Kioku (記憶)

Second brain for your repositories. Kioku brings repository briefings, documents,
Notion pages, indexed code, agent journals, and source-linked learnings into a
folder-scoped workspace for developers and coding agents.

Use the web app to organize knowledge and chat with it, or connect Claude Code,
Codex, and other MCP clients. Supabase provides authentication, PostgreSQL,
pgvector, and private file storage. Kioku is self-hosted.

## Start here

- **Connect a repository:** [CLI installation and usage](cli/README.md).
- **Run Kioku locally:** [development setup](docs/development.md).
- **Understand the system:** [architecture and retrieval](docs/architecture.md).
- **Operate a deployment:** [deployment and recovery](docs/operations.md).
- **Browse every documentation area:** [documentation index](docs/README.md).

## Repository workflow

1. Create a repository folder in the web app.
2. Upload its specifications and architecture notes, or connect Notion.
3. Install the CLI, sign in with `kioku login`, then run `kioku init` in the repo.
   Use `kioku init --agent codex` to select Codex explicitly.
4. Start your coding agent. The session hook loads the repository briefing;
   MCP tools retrieve scoped documents and code when more detail is needed.
5. After adding context, use `kioku init --force` to regenerate the briefing.

The Stop hook captures daily Markdown journals asynchronously. `kioku memory-sync`
retries uploads after an offline session. Manabi reports machine presence and
repository inventory; Mihari indexes cloud repositories and refreshes knowledge.
See [journals, learnings, and originals](docs/agent-memory.md) for their boundaries.

## Capabilities on main

- Hybrid document retrieval, code candidates, Voyage reranking, and neighboring
  document chunks; graph tools for definitions, references, outlines, and impact.
- Streaming chat with knowledge, metadata, and web-search tools.
- API-backed generation plus explicitly enabled Tsukai subscription execution,
  durable native chat recovery, and authenticated model discovery.
- Nested folders, uploads, document viewing, notes, pinned context, Notion sync,
  GitHub repository registration, and scoped API keys for external ingestion.
- Repository briefings, architecture documentation, daily journals, and learnings.
- Retrieval evaluation and backend, frontend, CLI, release, and Tsukai checks.

Merged support does not mean every deployment has enabled it. Tsukai requires
explicit owner/task configuration; it does not silently fall back to API billing
when an admitted native execution fails. Original transcript archiving is tracked
in open PRs, not advertised as available on main. See [change status](docs/change-status.md).

## Services

| Surface | Responsibility | Entry point |
| --- | --- | --- |
| Backend | Authentication, REST, chat, ingestion coordination | [backend](backend/README.md) |
| Worker | Queued parsing and background work | [local setup](docs/development.md) |
| MCP | Scoped knowledge and code tools | [integration guide](docs/integrations.md) |
| Frontend | Workspace, documents, chat, settings | [frontend](frontend/README.md) |
| CLI / Manabi | Agent setup, hooks, machine presence | [CLI](cli/README.md) |
| Mihari | Repository polling and knowledge refresh | [Mihari](mihari/README.md) |
| Tsukai | Durable native Claude Code execution | [Tsukai](tsukai/README.md) |

## Contributing

Use [development and validation commands](docs/development.md). Keep operational
guides grounded in merged code, and identify proposals and research explicitly.
Package manifests and release tags are the version source; the docs avoid a second
manually maintained version table.

## License

MIT, as declared in package metadata.
