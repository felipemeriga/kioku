/**
 * Everything that touches the Claude Code project surface — .mcp.json,
 * .claude/settings.json (SessionStart hook), CLAUDE.md.
 *
 * All three writes are idempotent: rerunning `init` never duplicates
 * content. We detect our sections by fenced markers.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";

const MARKER_BEGIN = "<!-- BEGIN kioku second-brain instructions -->";
const MARKER_END = "<!-- END kioku second-brain instructions -->";

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

const SESSION_START_COMMAND = "kioku session-start";
const STOP_COMMAND = "kioku capture";

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
  command: string
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
  bucket[event] = groups;
  const already = groups.some((g) =>
    g.hooks.some((h) => h.command === command)
  );
  if (!already) groups.push({ hooks: [{ type: "command", command }] });
  // Return true if we changed anything (added the hook OR pruned bad entries).
  return !already || raw.length !== groups.length;
}

/** Remove a specific command hook (both the correct group shape and the legacy
 *  `{type,command}`-directly form) from a settings file. Used to migrate kioku's
 *  hooks OUT of the committed settings.json. No-op if the file/hook is absent.
 *  Never creates the file. Returns true if it changed. */
function removeHookFromFile(
  path: string,
  event: string,
  command: string
): boolean {
  if (!existsSync(path)) return false;
  const settings = loadSettings(path);
  const arr = settings.hooks?.[event];
  if (!Array.isArray(arr)) return false;
  const before = JSON.stringify(arr);
  const cleaned = (arr as unknown[]).filter((g) => {
    if (!g || typeof g !== "object") return false;
    const o = g as { type?: string; command?: string; hooks?: HookEntry[] };
    if (o.type === "command") return o.command !== command; // legacy malformed
    if (Array.isArray(o.hooks))
      return !o.hooks.some((h) => h.command === command);
    return true; // unknown shape — leave it
  }) as HookGroup[];
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
  command: string
): { path: string; addedHook: boolean } {
  const dir = join(repoRoot, ".claude");
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const path = join(dir, "settings.local.json");
  const settings = loadSettings(path);
  const added = ensureHook(settings, event, command);
  writeFileSync(path, JSON.stringify(settings, null, 2) + "\n");
  // Migration: strip any old copy from the committed settings.json.
  removeHookFromFile(join(dir, "settings.json"), event, command);
  return { path, addedHook: added };
}

export function installSessionStartHook(repoRoot: string): {
  path: string;
  addedHook: boolean;
} {
  return installHook(repoRoot, "SessionStart", SESSION_START_COMMAND);
}

export function installStopHook(repoRoot: string): {
  path: string;
  addedHook: boolean;
} {
  return installHook(repoRoot, "Stop", STOP_COMMAND);
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

// ── CLAUDE.md snippet ────────────────────────────────────────────

const CLAUDE_MD_SNIPPET = `${MARKER_BEGIN}

## Kioku second-brain

You have an \`kioku\` MCP server wired to this repo. It gives you
persistent memory across sessions and PC switches.

### At session start

The SessionStart hook fetches your briefing automatically. Every 10
minutes or every 5 assistant turns (whichever comes first), the Stop
hook automatically distills recent turns into Mem0 — preferences,
findings, decisions, issues, and session summaries.

If you want to reload the briefing manually:

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

export function updateClaudeMd(repoRoot: string): {
  path: string;
  action: "created" | "appended" | "updated";
} {
  const path = join(repoRoot, "CLAUDE.md");
  if (!existsSync(path)) {
    writeFileSync(path, CLAUDE_MD_SNIPPET);
    return { path, action: "created" };
  }
  const existing = readFileSync(path, "utf8");
  if (existing.includes(MARKER_BEGIN) && existing.includes(MARKER_END)) {
    // Update the existing block in place.
    const before = existing.slice(0, existing.indexOf(MARKER_BEGIN));
    const after = existing.slice(
      existing.indexOf(MARKER_END) + MARKER_END.length
    );
    writeFileSync(path, before + CLAUDE_MD_SNIPPET + after);
    return { path, action: "updated" };
  }
  // Append — preserve any trailing newlines the user already has.
  const sep = existing.endsWith("\n") ? "\n" : "\n\n";
  writeFileSync(path, existing + sep + CLAUDE_MD_SNIPPET);
  return { path, action: "appended" };
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
    ".claude/kioku-autogen.lock",
    ".claude/kioku-autogen.log",
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
