/**
 * Everything that touches the Claude Code project surface — .mcp.json,
 * .claude/settings.json (SessionStart hook), CLAUDE.md.
 *
 * All three writes are idempotent: rerunning `init` never duplicates
 * content. We detect our sections by fenced markers.
 */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  chmodSync,
  realpathSync,
} from "node:fs";
import { join, dirname, isAbsolute } from "node:path";
import { execFileSync } from "node:child_process";

export const MARKER_BEGIN = "<!-- BEGIN kioku second-brain instructions -->";
export const MARKER_END = "<!-- END kioku second-brain instructions -->";

// ── .mcp.json ─────────────────────────────────────────────────────

export interface McpConfig {
  mcpServers: Record<
    string,
    {
      type?: string;
      url: string;
      headers?: Record<string, string>;
      command?: string;
      args?: string[];
    }
  >;
}

export function writeMcpConfig(
  repoRoot: string,
  serverEntry: { url: string; headers: Record<string, string>; type?: string }
): { path: string; existed: boolean } {
  const path = join(repoRoot, ".mcp.json");
  let existing: McpConfig = { mcpServers: {} };
  const existed = existsSync(path);
  if (existed) {
    try {
      existing = JSON.parse(readFileSync(path, "utf8")) as McpConfig;
      if (!existing.mcpServers) existing.mcpServers = {};
    } catch {
      // File exists but not valid JSON — back it up.
      writeFileSync(`${path}.backup`, readFileSync(path));
      existing = { mcpServers: {} };
    }
  }
  // Force type:"sse" — Claude Code needs it to load a remote MCP server;
  // without it the entry is parsed as stdio and skipped. Writing it here (not
  // just trusting the backend) means re-running `init` repairs older repos
  // whose .mcp.json predates this fix.
  existing.mcpServers["kioku"] = { type: "sse", ...serverEntry };
  writeFileSync(path, JSON.stringify(existing, null, 2) + "\n");
  return { path, existed };
}

// ── .claude/settings.json — SessionStart hook ─────────────────────

// Claude Code hooks schema: each event maps to an array of GROUPS, and each
// group is { matcher?, hooks: [ { type: "command", command } ] }. Writing the
// command entry directly into the event array (no `hooks` wrapper) makes Claude
// Code reject the whole settings file ("Expected array, but received undefined").
interface HookEntry {
  type: "command";
  command: string;
}
interface HookGroup {
  matcher?: string;
  hooks: HookEntry[];
}
interface ClaudeSettings {
  hooks?: { [event: string]: HookGroup[] | undefined };
  [k: string]: unknown;
}

// Hooks are identified by their kioku subcommand. The actual command string is
// built absolute (see cliInvocation) so it runs from shells without nvm/custom
// PATH — Claude Code runs hooks via /bin/sh and git runs its hooks via sh too,
// neither of which loads the user's interactive PATH. A bare `kioku` fails there
// whenever kioku is installed under nvm.
export const SUB_SESSION_START = "session-start";
export const SUB_STOP = "capture";
export const SUB_POST_PUSH = "on-push";
const SUB_INDEX = "index";

/** Single-quote a path for /bin/sh. */
export function shQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

/** Absolute `<node> <entry.js>` for this running CLI, sh-quoted. PATH-independent
 *  so hook shells (/bin/sh, git) resolve it even without nvm on PATH. Falls back
 *  to bare `kioku` only if the entry script can't be resolved (very unusual).
 *  Note: pinned to the current node install path; re-run `kioku init` after
 *  switching node versions (e.g. `nvm install`) to refresh it. */
export function cliInvocation(): string {
  const argv1 = process.argv[1];
  if (!argv1) return "kioku"; // no entry script (unusual) — best-effort bare
  let entry = argv1;
  try {
    entry = realpathSync(argv1); // resolve the nvm bin symlink to the real file
  } catch {
    entry = argv1; // keep as-is if it can't be resolved
  }
  return `${shQuote(process.execPath)} ${shQuote(entry)}`;
}

/** Build the full hook command for a subcommand. */
function hookCommand(subcommand: string): string {
  return `${cliInvocation()} ${subcommand}`;
}

/** True if `cmd` is a kioku invocation of `subcommand` — matches both the
 *  legacy bare form (`kioku session-start`) and the absolute form. Used to
 *  dedupe/migrate on re-init. */
function isSubcommand(cmd: string | undefined, subcommand: string): boolean {
  return !!cmd && cmd.trim().endsWith(` ${subcommand}`);
}

function loadSettings(path: string): ClaudeSettings {
  if (!existsSync(path)) return {};
  try {
    return JSON.parse(readFileSync(path, "utf8")) as ClaudeSettings;
  } catch {
    writeFileSync(`${path}.backup`, readFileSync(path));
    return {};
  }
}

/** Idempotently install a command hook in the correct group shape, and drop any
 *  malformed entries (e.g. the old `{type,command}`-directly form a prior CLI
 *  version wrote) so Claude Code doesn't reject the file. */
function ensureHook(
  settings: ClaudeSettings,
  event: string,
  command: string,
  subcommand: string,
  matcher?: string
): boolean {
  if (!settings.hooks) settings.hooks = {};
  const bucket = settings.hooks;
  const raw = Array.isArray(bucket[event]) ? (bucket[event] as unknown[]) : [];
  // Keep only well-formed groups (an object with a `hooks` array); this drops
  // the legacy malformed entries this tool used to write.
  const groups = raw.filter(
    (g): g is HookGroup =>
      !!g && typeof g === "object" && Array.isArray((g as HookGroup).hooks)
  );
  // Strip any existing kioku hook for THIS subcommand — both the exact current
  // command and stale variants (e.g. the old bare `kioku session-start`, or an
  // absolute command from a prior node version). This migrates re-inits to the
  // current invocation instead of stacking duplicates.
  let hadExact = false;
  let removedStale = false;
  for (const g of groups) {
    g.hooks = g.hooks.filter((h) => {
      if (h.command === command) {
        hadExact = true;
        return true;
      }
      if (isSubcommand(h.command, subcommand)) {
        removedStale = true;
        return false;
      }
      return true;
    });
  }
  // Drop groups emptied by the strip.
  const kept = groups.filter((g) => g.hooks.length > 0);
  bucket[event] = kept;
  if (!hadExact) {
    // Tool-scoped events (e.g. PostToolUse) need a matcher so the group only
    // fires for the intended tool; SessionStart/Stop take none.
    const group: HookGroup = { hooks: [{ type: "command", command }] };
    if (matcher) group.matcher = matcher;
    kept.push(group);
  }
  // Changed if we added the hook, removed a stale variant, or pruned bad groups.
  return !hadExact || removedStale || raw.length !== groups.length;
}

/** Remove a specific command hook (both the correct group shape and the legacy
 *  `{type,command}`-directly form) from a settings file. Used to migrate kioku's
 *  hooks OUT of the committed settings.json. No-op if the file/hook is absent.
 *  Never creates the file. Returns true if it changed. */
function removeHookFromFile(
  path: string,
  event: string,
  subcommand: string
): boolean {
  if (!existsSync(path)) return false;
  const settings = loadSettings(path);
  const arr = settings.hooks?.[event];
  if (!Array.isArray(arr)) return false;
  const before = JSON.stringify(arr);
  const cleaned = (arr as unknown[])
    .map((g) => {
      if (!g || typeof g !== "object") return g;
      const o = g as { type?: string; command?: string; hooks?: HookEntry[] };
      if (o.type === "command")
        return isSubcommand(o.command, subcommand) ? null : g; // legacy malformed
      if (Array.isArray(o.hooks)) {
        o.hooks = o.hooks.filter((h) => !isSubcommand(h.command, subcommand));
        return o.hooks.length > 0 ? g : null;
      }
      return g; // unknown shape — leave it
    })
    .filter((g): g is HookGroup => g !== null && g !== undefined);
  if (JSON.stringify(cleaned) === before) return false;
  settings.hooks![event] = cleaned;
  writeFileSync(path, JSON.stringify(settings, null, 2) + "\n");
  return true;
}

/** Install a personal command hook. Writes to the per-user, gitignored
 *  `.claude/settings.local.json` (NOT the committed settings.json, which is
 *  team-shared), and migrates any prior copy out of settings.json. */
function installHook(
  repoRoot: string,
  event: string,
  subcommand: string,
  matcher?: string
): { path: string; addedHook: boolean } {
  const dir = join(repoRoot, ".claude");
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const path = join(dir, "settings.local.json");
  const settings = loadSettings(path);
  const added = ensureHook(
    settings,
    event,
    hookCommand(subcommand),
    subcommand,
    matcher
  );
  writeFileSync(path, JSON.stringify(settings, null, 2) + "\n");
  // Migration: strip any old copy from the committed settings.json.
  removeHookFromFile(join(dir, "settings.json"), event, subcommand);
  return { path, addedHook: added };
}

export function installSessionStartHook(repoRoot: string): {
  path: string;
  addedHook: boolean;
} {
  return installHook(repoRoot, "SessionStart", SUB_SESSION_START);
}

export function installStopHook(repoRoot: string): {
  path: string;
  addedHook: boolean;
} {
  return installHook(repoRoot, "Stop", SUB_STOP);
}

/** PostToolUse hook scoped to the Bash tool. `kioku on-push` filters for a
 *  `git push` command and, when found, nudges the session to refresh the
 *  repo's stored `activity` briefing from the newly-pushed commits. */
export function installPostPushHook(repoRoot: string): {
  path: string;
  addedHook: boolean;
} {
  return installHook(repoRoot, "PostToolUse", SUB_POST_PUSH, "Bash");
}

// ── native git pre-push hook ──────────────────────────────────────────
//
// The Claude Code PostToolUse hook only fires when the AGENT runs `git push`.
// A native git pre-push hook fires on EVERY push (any terminal), so the code
// graph stays fresh even when the developer pushes by hand. Runs `kioku index`
// detached — non-blocking, best-effort, never fails the push. The per-repo
// index lock keeps it from double-indexing with the agent's on-push hook.

const GIT_HOOK_MARKER = "# kioku: refresh code graph on push";

/** Resolve the repo's effective hooks dir (honors core.hooksPath). */
function gitHooksDir(repoRoot: string): string {
  try {
    const rel = execFileSync("git", ["rev-parse", "--git-path", "hooks"], {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return isAbsolute(rel) ? rel : join(repoRoot, rel);
  } catch {
    return join(repoRoot, ".git", "hooks");
  }
}

export function installPrePushGitHook(repoRoot: string): {
  path: string;
  addedHook: boolean;
} {
  const dir = gitHooksDir(repoRoot);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const path = join(dir, "pre-push");

  // Absolute invocation — a bare `kioku` isn't on git's hook-shell PATH under
  // nvm. Backgrounded + output discarded so it never blocks or fails the push.
  const block = [
    GIT_HOOK_MARKER,
    "# Installed by `kioku init` — non-blocking, best-effort.",
    `( ${hookCommand(SUB_INDEX)} >/dev/null 2>&1 & )`,
    "# end kioku",
  ].join("\n");

  if (existsSync(path)) {
    const existing = readFileSync(path, "utf8");
    if (existing.includes(GIT_HOOK_MARKER)) {
      // Migrate/refresh our block in place (e.g. old bare `kioku index`
      // -> absolute invocation) without touching the rest of the hook.
      const lines = existing.split("\n");
      const start = lines.findIndex((l) => l.includes(GIT_HOOK_MARKER));
      let end = lines.findIndex(
        (l, i) => i >= start && l.trim() === "# end kioku"
      );
      if (end === -1) end = start; // malformed — replace just the marker line
      lines.splice(start, end - start + 1, block);
      const updated = lines.join("\n");
      if (updated === existing) return { path, addedHook: false };
      writeFileSync(path, updated);
      chmodSync(path, 0o755);
      return { path, addedHook: true };
    }
    // Coexist: insert our block after the shebang without altering the existing
    // hook's control flow (we background + never add our own exit).
    const lines = existing.split("\n");
    const at = lines[0]?.startsWith("#!") ? 1 : 0;
    lines.splice(at, 0, "", block, "");
    writeFileSync(path, lines.join("\n"));
    chmodSync(path, 0o755);
    return { path, addedHook: true };
  }

  writeFileSync(path, `#!/bin/sh\n\n${block}\n\nexit 0\n`);
  chmodSync(path, 0o755);
  return { path, addedHook: true };
}

/** Write the per-repo state file. Contains the folder_id the CLI bound
 *  this repo to plus capture watermarks. Not a secret — the api key is
 *  in .mcp.json — but still gitignored to avoid state churn in git. */
export function writeCaptureState(
  repoRoot: string,
  state: {
    folder_id: string;
    folder_name: string;
    scope_root_name: string;
    api_key_minted_at?: string;
    // HEAD at init time — the `on-push` hook only nudges for commits made
    // after this, so the first push doesn't re-summarize history already
    // covered by the initial activity generation.
    last_activity_sha?: string;
  }
): { path: string } {
  const dir = join(repoRoot, ".claude");
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const path = join(dir, "kioku-state.json");
  // Preserve any watermarks from prior sessions.
  let existing: Record<string, unknown> = {};
  if (existsSync(path)) {
    try {
      existing = JSON.parse(readFileSync(path, "utf8")) as Record<
        string,
        unknown
      >;
    } catch {
      existing = {};
    }
  }
  const merged = { ...existing, ...state };
  writeFileSync(path, JSON.stringify(merged, null, 2) + "\n");
  return { path };
}

/** Read the bits of kioku-state.json init cares about — the bound folder and
 *  when this repo's api key was last minted. */
export function readRepoState(repoRoot: string): {
  folder_id?: string;
  api_key_minted_at?: string;
} | null {
  const path = join(repoRoot, ".claude", "kioku-state.json");
  if (!existsSync(path)) return null;
  try {
    return JSON.parse(readFileSync(path, "utf8")) as {
      folder_id?: string;
      api_key_minted_at?: string;
    };
  } catch {
    return null;
  }
}

/** Read the existing kioku MCP entry + plaintext api key from .mcp.json, if
 *  present. Lets init reuse a recently-minted key instead of rotating it. */
export function readMcpEntry(repoRoot: string): {
  entry: { url: string; headers: Record<string, string> };
  key: string;
} | null {
  const path = join(repoRoot, ".mcp.json");
  if (!existsSync(path)) return null;
  try {
    const cfg = JSON.parse(readFileSync(path, "utf8")) as McpConfig;
    const entry = cfg.mcpServers?.["kioku"];
    const auth = entry?.headers?.["Authorization"];
    if (!entry?.url || !auth) return null;
    const key = auth.replace(/^Bearer\s+/, "");
    if (!key) return null;
    return { entry: { url: entry.url, headers: entry.headers ?? {} }, key };
  } catch {
    return null;
  }
}

export function readLastSessionAt(repoRoot: string): string | undefined {
  const path = join(repoRoot, ".claude", "kioku-state.json");
  if (!existsSync(path)) return undefined;
  try {
    const s = JSON.parse(readFileSync(path, "utf8")) as {
      last_session_at?: string;
    };
    return s.last_session_at;
  } catch {
    return undefined;
  }
}

export function stampLastSessionAt(repoRoot: string, iso: string): void {
  const dir = join(repoRoot, ".claude");
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const path = join(dir, "kioku-state.json");
  let existing: Record<string, unknown> = {};
  if (existsSync(path)) {
    try {
      existing = JSON.parse(readFileSync(path, "utf8")) as Record<
        string,
        unknown
      >;
    } catch {
      existing = {};
    }
  }
  writeFileSync(
    path,
    JSON.stringify({ ...existing, last_session_at: iso }, null, 2) + "\n"
  );
}

// ── CLAUDE.md / AGENTS.md snippet ─────────────────────────────────
//
// The instructional block is agent-neutral except for two sentences about
// which hooks are wired. `secondBrainSnippet` builds it for a given agent so
// CLAUDE.md and AGENTS.md share one source of truth.

/** Build the fenced second-brain instructions block. `pushHook` toggles the
 *  sentence about the git-push activity-refresh hook, which only the Claude
 *  Code surface installs (Codex wires just SessionStart + Stop). */
export function secondBrainSnippet(opts: { pushHook: boolean }): string {
  const pushLine = opts.pushHook
    ? `After a \`git push\`, a PostToolUse hook asks you to refresh this repo's
\`activity\` briefing from the newly-pushed commits (via
\`update_folder_briefing_section\`) so the web UI stays current — just
follow the injected instruction when you see it.

`
    : "";
  return `${MARKER_BEGIN}

## Kioku second-brain

You have an \`kioku\` MCP server wired to this repo. It gives you
persistent memory across sessions and PC switches.

### At session start

The SessionStart hook fetches your briefing automatically. Every 10
minutes or every 5 assistant turns (whichever comes first), the Stop
hook automatically distills recent turns into Mem0 — preferences,
findings, decisions, issues, and session summaries.

${pushLine}If you want to reload the briefing manually:

- \`get_folder_briefing()\` — 9-section briefing for this repo
  (overview, architecture, preferences, important_files, how_it_runs,
   deployment, dependencies, activity, documentation)
- \`get_folder_orientation()\` — broader context for this repo's
  folder subtree
- \`list_folders_in_scope()\` — see what folders exist under this
  repo's scope

### When you learn something worth keeping

Persist it. It'll survive the session, the PC, the team:

- \`save_memory(content, category='preference')\` — eternal rules of thumb
  (\"never use Co-Authored-By\", \"backend uses uv\"). Prepended to
  every future briefing.
- \`save_memory(content, category='finding' | 'decision' | 'issue' | 'session')\`
  — episodic learnings. Show up in \`recent_activity\`.
- \`update_folder_briefing_section(section, content, pin=True)\` — for
  structured facts about the repo (deploy steps, important files,
  architecture). Pinned sections survive auto-regen.

### When you need info you don't have in this window

- \`knowledge_base_search(query)\` — searches docs + Mem0 across the
  scope subtree. Grounded, cited.
- \`search_memory(query)\` — Mem0 only, faster for preference-style
  lookups.
- \`query_documents_metadata(question)\` — structured questions about
  what documents exist ("show me all PDFs added this week").
- \`read_folder_documents()\` — full text of every doc already uploaded to
  this folder (specs, architecture, ecosystem context beyond the code).

### Navigating the code — query the graph, don't grep

This repo is indexed into a code graph. Prefer these over \`grep\`/\`glob\`
to locate and trace code — they return exact \`file:line\` answers:

- \`find_definition(symbol)\` — where a function/type/method is defined.
- \`find_references(symbol)\` — who calls/uses it (all sites).
- \`outline(path)\` — the symbols under a file or directory.
- \`impact_of(symbol)\` — blast radius: what transitively depends on it.

The graph refreshes on \`git push\` (and via \`kioku index\`). If a lookup
returns nothing, fall back to a normal search.

### Convention

Prefer \`update_folder_briefing_section\` for repo facts, \`save_memory\`
for preferences and one-off learnings. If uncertain, save both — briefings
are pinned by default and won't be overwritten.

If a briefing feels thin, this repo's kioku folder may have no uploaded docs.
Suggest the user add documents or connect Notion in the web UI, then re-run
\`kioku init --force\` — generation folds that ecosystem context into the
briefing and the detailed doc, so it spans the whole ecosystem, not just code.

${MARKER_END}
`;
}

const CLAUDE_MD_SNIPPET = secondBrainSnippet({ pushHook: true });

/** Idempotently write a fenced snippet into a markdown file — create it, update
 *  the existing block in place, or append. Shared by CLAUDE.md and AGENTS.md. */
export function upsertMarkdownSnippet(
  path: string,
  snippet: string
): { path: string; action: "created" | "appended" | "updated" } {
  if (!existsSync(path)) {
    writeFileSync(path, snippet);
    return { path, action: "created" };
  }
  const existing = readFileSync(path, "utf8");
  if (existing.includes(MARKER_BEGIN) && existing.includes(MARKER_END)) {
    // Update the existing block in place.
    const before = existing.slice(0, existing.indexOf(MARKER_BEGIN));
    const after = existing.slice(
      existing.indexOf(MARKER_END) + MARKER_END.length
    );
    writeFileSync(path, before + snippet + after);
    return { path, action: "updated" };
  }
  // Append — preserve any trailing newlines the user already has.
  const sep = existing.endsWith("\n") ? "\n" : "\n\n";
  writeFileSync(path, existing + sep + snippet);
  return { path, action: "appended" };
}

export function updateClaudeMd(repoRoot: string): {
  path: string;
  action: "created" | "appended" | "updated";
} {
  return upsertMarkdownSnippet(join(repoRoot, "CLAUDE.md"), CLAUDE_MD_SNIPPET);
}

// ── .gitignore ────────────────────────────────────────────────────

export function updateGitignore(repoRoot: string): {
  path: string;
  changed: boolean;
} {
  const path = join(repoRoot, ".gitignore");
  const entries = [
    ".mcp.json",
    ".claude/settings.local.json",
    ".claude/kioku-state.json",
    ".claude/kioku-capture.log",
    ".claude/kioku-onpush.log",
    ".claude/kioku-autogen.lock",
    ".claude/kioku-autogen.log",
    // Graphify's local extraction output + AST cache (used by `kioku index`).
    "graphify-out/",
  ];
  const existing = existsSync(path) ? readFileSync(path, "utf8") : "";
  const missing = entries.filter(
    (e) => !existing.split("\n").some((line) => line.trim() === e)
  );
  if (missing.length === 0) return { path, changed: false };
  const block = ["", "# kioku CLI", ...missing, ""].join("\n");
  writeFileSync(path, existing + block);
  return { path, changed: true };
}
