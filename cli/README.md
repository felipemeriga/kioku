# kioku

CLI that wires a local repo to your **kioku** second-brain — installs the MCP server, session hooks, and CLAUDE.md snippet so Claude Code loads your briefing at session start and captures learnings back to Mem0.

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

That's it. Open Claude Code in `~/repos/my-project` and the SessionStart hook loads your briefing automatically. Stop hook captures learnings every ~10 min or every 5 turns.

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
| `.claude/settings.json` | `SessionStart` + `Stop` hooks | (committable) |
| `.claude/kioku-state.json` | folder_id + capture watermark | ✓ |
| `CLAUDE.md` | Instructions for Claude on when to save memories vs. update the briefing | (committable) |
| `.gitignore` | Adds the 4 above ✓ entries | (committable) |

### `session-start`

Run automatically by the SessionStart hook. Reads `.mcp.json`, hits `/api/cli/scope-info`, prints a compact context block Claude Code prepends to the session:

```
── kioku second-brain ──
Scope: personal
Folders in scope: 3
Repos: personal/my-project, personal/other-repo
Tools available: get_folder_briefing, get_folder_orientation, list_folders_in_scope, save_memory, search_memory, knowledge_base_search
Call get_folder_briefing() to load the 8-section briefing.
─────────────────────────────────
```

You never call this by hand, but it's useful for testing your setup.

### `capture`

Run automatically by the Stop hook after every assistant turn. Debounced — fires only when **5 new turns** OR **10 minutes** since the last fire. Reads Claude Code's transcript, ships the delta, backend distills to 0-3 memory entries via Haiku (categories: `preference` / `finding` / `decision` / `issue` / `session`), Mem0 stores with content-hash dedup.

Silent on failure. Set `KIOKU_DEBUG=1` to log to `.claude/kioku-capture.log`.

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

**Hook errors in Claude Code** — Set `KIOKU_DEBUG=1` in your shell and re-run. Debug output goes to `.claude/kioku-capture.log`.

**Anything else** — `kioku doctor` will tell you what's wrong and what to run.
