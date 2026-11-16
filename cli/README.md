# Kioku CLI

Connect a repository to Kioku, configure Claude Code/Codex, retrieve knowledge,
and capture daily journals. Manabi reports machine presence and repo inventory.

## Install

Standalone macOS/Linux installation (no Node runtime required):

```sh
curl -fsSL https://raw.githubusercontent.com/felipemeriga/kioku/main/scripts/release/install.sh | sh
```

The installer verifies the release checksum and installs to `~/.local/bin`.
Use `KIOKU_VERSION` to pin a release or `KIOKU_INSTALL_DIR` to choose the destination.
Windows x64 users can run `install.ps1` from the
[CLI release](https://github.com/felipemeriga/kioku/releases).

The npm package is `@felipemeriga/kioku` (Node.js 18+):

```bash
npm install -g @felipemeriga/kioku
```

To build this checkout, run `npm ci && npm run build && npm link` in `cli/`.
Interactive standalone `init` can offer an update; rerun init afterward.

## Sign in and connect

```bash
kioku login                     # browser authorization handoff
cd ~/repos/my-project
kioku init                      # detect agent and bind repository
kioku init --agent codex         # explicitly select Codex
```

`kioku login --no-browser` prints the authorization URL. The CLI waits for browser
approval; it does not prompt for an email OTP. `kioku quickstart` combines login
and setup. Add ecosystem docs or Notion content to the repository folder before
initializing for a richer briefing.

Supported init options include `--root <name>`, `--yes`, `--force`,
`--agent <claude|codex>`, and `--codex`. Run `kioku init --help` for current flags.
GitHub registration is handled by the current setup flow; removed token/skip flags
from older CLI versions should not be copied into scripts.

Init configures the selected agent's MCP and SessionStart integration, installs
journal Stop hooks for both supported agents, updates repository instructions,
and registers the machine/repository with Manabi. Reinitialization preserves other
agent configuration. Codex hook trust remains host-controlled.

## Server selection

The default REST server is `https://kioku.api.merigafy.com`. For local development:

```bash
export KIOKU_API_BASE=http://localhost:8000
export KIOKU_MCP_URL=http://localhost:8001/sse
```

Precedence is `--api-base` / `KIOKU_API_BASE`, persisted `api_base`, then the hosted
default. Set the MCP override explicitly for custom deployments rather than
assuming a domain transformation. Codex setup converts the SSE URL to its
streamable HTTP MCP path.

## Commands

| Command | Purpose |
| --- | --- |
| `quickstart`, `login`, `logout` | Guided setup and browser authorization |
| `init` | Bind repo, configure agent, register indexing/presence |
| `status`, `doctor`, `whoami` | Binding, connectivity, and identity checks |
| `ls [path]` | Browse workspace folders; supports `--json` |
| `briefing` | Read briefing; `--section <name>` or `--json` |
| `search <query...>` | Search documents/code; `--folder`, `--limit`, `--json` |
| `open [target]` | Open the web UI; `--json` prints its URL |
| `index` | Extract and upload the current repo's code graph |
| `memory-sync` | Retry local daily-journal uploads |
| `session-start`, `on-push` | Hook-facing helpers; normally automatic/legacy |

Global options include `--quiet`, `--no-color`, and `--api-base`. `NO_COLOR`,
`KIOKU_QUIET`, and `KIOKU_DEBUG` control output and diagnostics. Check each command's
`--help` before automating options.

## Journals and presence

Stop hooks start detached summarizers and append `.kioku/memory/YYYY-MM-DD.md`.
The daily file syncs to private Storage, separately from document embeddings.
Offline files remain local for `kioku memory-sync`. See
[journals and original-evidence status](../docs/agent-memory.md).

Manabi runs as a per-user login service, reconnects with bounded backoff, and
reports current/last-known inventory. It does not crawl session transcripts.
See [Manabi lifecycle and troubleshooting](../docs/manabi.md).

## Files and credentials

| Location | Content |
| --- | --- |
| `~/.config/kioku/config.json` (or XDG config directory) | REST URL, access/refresh tokens, identity; mode 0600 |
| `.mcp.json` | Repository MCP URL and scoped bearer key; private and gitignored |
| `.claude/settings.local.json` | Claude Code hooks |
| `.claude/kioku-state.json` | Repository binding and local activity state |
| `~/.codex/config.toml` (or `CODEX_HOME`) | Codex MCP configuration and hooks, including its key |
| `CLAUDE.md` / `AGENTS.md` | Agent instructions for the selected integration |
| `.kioku/memory/` | Daily journals and local capture/sync state |
| `~/.config/kioku/manabi/` (or XDG config directory) | Machine credential and bounded diagnostic state |

The CLI stores credentials locally. Protect these paths; do not commit MCP keys,
login tokens, or machine credentials. `logout` clears login/connection credentials;
it does not imply that every local journal/config artifact has been erased.

## Troubleshooting and development

Run `kioku doctor` for backend, MCP, login, and repository binding diagnostics.
Use `kioku status` for the last local machine connection report. Sign in again
when authorization expires; rerun init to repair agent/service setup. Sleeping or
logged-out machines may be offline until their login service resumes.

`npm test` builds and runs CLI tests. See [development](../docs/development.md),
[operations](../docs/operations.md), and the [documentation index](../docs/README.md).
