# kioku

CLI that wires a local repo to your **kioku** second-brain — installs the MCP server, session hooks, and CLAUDE.md snippet so Claude Code loads your briefing at session start.

```text
  ● kioku  second-brain for coding agents
  ────────────────────────────────────────
```

## Install

Pick one:

```bash
# via npx (no install, always latest)
npx kioku@latest login

# global install
npm install -g kioku
kioku login

# from source (until first npm publish)
git clone <this-repo>
cd kioku/cli && npm install && npm run build && npm link
```

## Quickstart

```bash
kioku login             # email + 6-digit code from your inbox
cd ~/repos/my-project
kioku init              # picks folder, wires MCP, installs hooks, done
```

That's it. Open Claude Code in `~/repos/my-project` and the SessionStart hook loads your briefing automatically.

## Environment

The CLI defaults to `http://localhost:8000` for the backend REST API. Point it elsewhere:

```bash
export KIOKU_API_BASE=https://api.your-domain.com
# The MCP URL is derived by swapping :8000 → :8001. Override if needed:
export KIOKU_MCP_URL=https://mcp.your-domain.com/sse
```

## Commands

### `login`

Sign in via email OTP.

```
? Email                          you@example.com
  · Sending code… done.
? 6-digit code from email        123456

  ╭──────────────────────────╮
  │ ✓ Signed in              │
  │   you@example.com        │
  │   3 root folders         │
  ╰──────────────────────────╯
```

Tokens stored at `~/.config/kioku/config.json` (0600). No password. No browser dance.

### `init`

Wires the current repo. Detects your git remote, figures out (or asks about) where in your workspace this repo lives, mints an API key, and writes 4 files. **Idempotent** — safe to re-run any time.

```bash
kioku init                          # interactive; smart defaults
kioku init --yes                    # no prompts, take all defaults
kioku init --root my-company        # pre-select a root by name
kioku init --github-token ghp_...   # explicit token (bypasses gh CLI detection)
kioku init --skip-github            # no GitHub sync (public-only briefing)
```

**Manabi connection**: `kioku init` also installs and starts one background Manabi
process for the current OS user. Subsequent repositories reuse it; no separate
start command is required. It maintains an authenticated outbound WebSocket to
the configured backend, sends heartbeats, and retries disconnected connections
indefinitely with exponential backoff and jitter (up to 60 seconds). Check
machine presence in **Remotes**. Each init also records the repository path and its
configured Claude Code/Codex providers in a local registry. Manabi syncs that current
inventory separately from document indexing. Re-initializing with another provider
keeps both configurations. This does not detect running agents or collect memories.

Existing bindings can be discovered from Claude's project index or Codex's configured
project paths, only when explicit Kioku markers exist and the current account owns
the repository folder. Manabi never crawls the disk or reads session transcripts.
Run init in an older project if it does not appear. Remotes shows OS logos, a friendly
computer name, and an optional name override that survives future init runs.

Missing paths and unreadable registries produce timestamped warnings. A corrupt
registry retains the server's last successful inventory; warnings clear after recovery.
Offline machines show last-known reports. `kioku status` also shows the last local
connection/startup report, including failures that cannot reach the backend.

Startup uses a macOS LaunchAgent, a Linux systemd user service, or a Windows
per-user login task with a periodic restart watchdog. These are **login services**,
not privileged boot services. Linux needs a working systemd user session; running
before login/after logout requires separately configured user lingering. macOS
installation requires a GUI login domain. Installation failures fail init with
an actionable error; re-running init repairs setup. Closing the terminal does
not stop Manabi, but sleep, shutdown, or logout can. It reconnects on return.

Manabi keeps its credential and a small runtime snapshot under
`~/.config/kioku/manabi` (or `$XDG_CONFIG_HOME/kioku/manabi`). It uses the current
Node executable through a stable absolute PATH link when available (for example,
Homebrew’s `bin/node` link), so replacing that Node version does not strand the
service on a deleted Cellar path. Keep Node installed; re-run init after moving
or removing the installation entirely. Standalone release builds
snapshot the Kioku executable instead and require no separate Node runtime. `kioku logout` clears the connection
credential; the supervised process idles until the next init. Machine credentials
only authorize presence and owned-repository inventory updates, not document or memory access.

Heartbeat timeouts use a monotonic clock. Suspension or a substantial wall-clock
change discards the old connection and reconnects. `status.json` holds the latest
local report; `diagnostics.json` keeps only the last 50 status transitions, with
codes and timestamps, without secrets or unbounded log growth. Storage failures
do not stop retries. Credential rejection retries at the capped interval, but
requires `kioku init` to repair registration. No process can connect while the
machine is asleep, shut down, or offline. An explicitly stopped/disabled OS service
stays under user control; Manabi does not reinstall itself or bypass that choice.
On Windows, disable or unregister the scheduled task to stop it deliberately;
ending its process alone is treated as a crash by the periodic watchdog.

**Smart defaults**: no prompt when there's an obvious answer.

- Only 1 root folder → uses it silently
- Root name matches your GitHub owner → uses it silently
- Empty root → creates the repo folder without asking
- Repo folder already exists as `kind='repo'` → attaches silently

**GitHub auth ladder** (in order of what's tried):

1. `--github-token <t>` flag
2. `gh auth token` (silent if you already ran `gh auth login`)
3. `GITHUB_TOKEN` or `GH_TOKEN` env var
4. Interactive PAT paste (opens `github.com/settings/tokens/new` with correct scopes pre-filled)

**Files written**:
| File | Purpose | Gitignored? |
|---|---|---|
| `.mcp.json` | Server config with SSE URL + Bearer API key | ✓ |
| `.claude/settings.local.json` | `SessionStart` hook | ✓ |
| `.claude/kioku-state.json` | folder_id + activity watermark | ✓ |
| `CLAUDE.md` | Instructions for Claude on using and updating the briefing | (committable) |
| `.gitignore` | Adds the 4 above ✓ entries | (committable) |

### `session-start`

Run automatically by the SessionStart hook. Reads `.mcp.json`, hits `/api/cli/scope-info`, prints a compact context block Claude Code prepends to the session:

```
── kioku second-brain ──
Scope: personal
Folders in scope: 3
Repos: personal/my-project, personal/other-repo
Tools available: get_folder_briefing, get_folder_orientation, list_folders_in_scope, knowledge_base_search
Call get_folder_briefing() to load the 8-section briefing.
─────────────────────────────────
```

You never call this by hand, but it's useful for testing your setup.

### `status`

Signed-in check + per-repo binding health:

```
  │ Status
  │
  · API base: http://localhost:8000
  ✓ Signed in as you@example.com  3 root folders

  │ This repo
  │
  · git: owner/repo
  ✓ .mcp.json wired
  ✓ SessionStart hook installed
  ✓ CLAUDE.md present
```

### `doctor`

Diagnostic. Runs every check + prints fix hints:

```
  │ System
  │
  ✓ Config file                    Signed in as you@example.com
  ✓ Backend reachable              http://localhost:8000 (HTTP 200)
  ✓ Login token                    3 root folder(s) visible
  ✓ MCP server reachable           http://localhost:8001
  ✓ gh CLI (optional)              Installed + authenticated

  │ This repo
  │
  · git: owner/repo
  ✓ .mcp.json
  ✓ .claude/settings.json
  ✓ CLAUDE.md
  ✓ .claude/kioku-state.json

  ✓ All checks passed.  Open Claude Code here — you're set.
```

If anything fails, the fix hint appears under it: `Run: kioku login`, `Start the backend`, `Run: gh auth login`, etc.

## Files & storage

**Global**: `~/.config/kioku/config.json` — login tokens only (0600).

**Per-repo**: everything in `.mcp.json`, `.claude/*.json`, `CLAUDE.md`. No secrets outside `.mcp.json` (which is gitignored).

**Server-side**: Folder metadata and documents are stored server-side. The CLI never persists secrets locally.

## Troubleshooting

**"Couldn't reach http://localhost:8000"** — Backend not running. Start it (or point at your prod URL with `KIOKU_API_BASE`).

**"Session expired"** — Your login token TTL'd out. `kioku login` again.

**"gh CLI is logged in but doesn't have access to X"** — Your gh account isn't a collaborator on that repo. Get access, or paste a PAT with `repo` scope.

**Hook errors in Claude Code** — Set `KIOKU_DEBUG=1` in your shell and re-run. Errors are printed by the SessionStart hook when debug logging is enabled.

**Anything else** — `kioku doctor` will tell you what's wrong and what to run.
