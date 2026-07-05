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
} from "node:fs";
import { join, dirname } from "node:path";

const MARKER_BEGIN = "<!-- BEGIN agentic-rag second-brain instructions -->";
const MARKER_END = "<!-- END agentic-rag second-brain instructions -->";

// ── .mcp.json ─────────────────────────────────────────────────────

export interface McpConfig {
  mcpServers: Record<
    string,
    { url: string; headers?: Record<string, string>; command?: string; args?: string[] }
  >;
}

export function writeMcpConfig(
  repoRoot: string,
  serverEntry: { url: string; headers: Record<string, string> },
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
  existing.mcpServers["agentic-rag"] = serverEntry;
  writeFileSync(path, JSON.stringify(existing, null, 2) + "\n");
  return { path, existed };
}

// ── .claude/settings.json — SessionStart hook ─────────────────────

interface ClaudeSettings {
  hooks?: {
    SessionStart?: Array<{
      type: "command";
      command: string;
      matcher?: string;
    }>;
    [k: string]: unknown;
  };
  [k: string]: unknown;
}

const HOOK_COMMAND = "agentic-rag session-start";

export function installSessionStartHook(repoRoot: string): {
  path: string;
  addedHook: boolean;
} {
  const dir = join(repoRoot, ".claude");
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  const path = join(dir, "settings.json");
  let settings: ClaudeSettings = {};
  if (existsSync(path)) {
    try {
      settings = JSON.parse(readFileSync(path, "utf8")) as ClaudeSettings;
    } catch {
      writeFileSync(`${path}.backup`, readFileSync(path));
      settings = {};
    }
  }
  if (!settings.hooks) settings.hooks = {};
  if (!settings.hooks.SessionStart) settings.hooks.SessionStart = [];
  const hooks = settings.hooks.SessionStart;
  const already = hooks.some((h) => h.command === HOOK_COMMAND);
  if (!already) {
    hooks.push({ type: "command", command: HOOK_COMMAND, matcher: "*" });
  }
  writeFileSync(path, JSON.stringify(settings, null, 2) + "\n");
  return { path, addedHook: !already };
}

// ── CLAUDE.md snippet ────────────────────────────────────────────

const CLAUDE_MD_SNIPPET = `${MARKER_BEGIN}

## Agentic RAG second-brain

You have an \`agentic-rag\` MCP server wired to this repo. It gives you
persistent memory across sessions and PC switches.

### At session start

The SessionStart hook fetches your briefing automatically. If you want
to reload it manually:

- \`get_folder_briefing()\` — 8-section briefing for this repo
  (overview, architecture, preferences, important_files, how_it_runs,
   deployment, dependencies, activity)
- \`get_folder_orientation()\` — broader workspace context if the
  api key is root-scoped (drills across sibling repos)
- \`list_folders_in_scope()\` — see what other folders/repos exist
  under this scope

### When you learn something worth keeping

Persist it. It'll survive the session, the PC, the team:

- \`save_memory(text, category='preference')\` — eternal rules of thumb
  (\"never use Co-Authored-By\", \"backend uses uv\"). Prepended to
  every future briefing.
- \`save_memory(text, category='finding' | 'decision' | 'issue' | 'session')\`
  — episodic learnings. Show up in \`recent_activity\`.
- \`update_folder_briefing_section(section, content, pin=True)\` — for
  structured facts about the repo (deploy steps, important files,
  architecture). Pinned sections survive auto-regen.

### When you need info you don't have in this window

- \`knowledge_base_search(query)\` — searches docs + Mem0 across the
  scope subtree. Grounded, cited.
- \`search_memory(query)\` — Mem0 only, faster for preference-style
  lookups.
- \`query_documents_metadata(query)\` — structured questions about
  what documents exist ("show me all PDFs added this week").

### Convention

Prefer \`update_folder_briefing_section\` for repo facts, \`save_memory\`
for preferences and one-off learnings. If uncertain, save both — briefings
are pinned by default and won't be overwritten.

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
    const after = existing.slice(existing.indexOf(MARKER_END) + MARKER_END.length);
    writeFileSync(path, before + CLAUDE_MD_SNIPPET + after);
    return { path, action: "updated" };
  }
  // Append — preserve any trailing newlines the user already has.
  const sep = existing.endsWith("\n") ? "\n" : "\n\n";
  writeFileSync(path, existing + sep + CLAUDE_MD_SNIPPET);
  return { path, action: "appended" };
}

// ── .gitignore ────────────────────────────────────────────────────

export function updateGitignore(repoRoot: string): { path: string; changed: boolean } {
  const path = join(repoRoot, ".gitignore");
  const entries = [".mcp.json", ".claude/settings.local.json"];
  const existing = existsSync(path) ? readFileSync(path, "utf8") : "";
  const missing = entries.filter((e) => !existing.split("\n").some((line) => line.trim() === e));
  if (missing.length === 0) return { path, changed: false };
  const block = ["", "# agentic-rag CLI", ...missing, ""].join("\n");
  writeFileSync(path, existing + block);
  return { path, changed: true };
}
