/**
 * Everything that touches the OpenAI Codex surface — the GLOBAL
 * ~/.codex/config.toml (MCP server + SessionStart/Stop hooks) and the
 * per-repo AGENTS.md instructions file.
 *
 * Mirrors claude.ts, but Codex config is a single global TOML file (not a
 * per-repo .mcp.json / .claude/settings.local.json). The hooks fire for every
 * Codex session; `kioku session-start` / `kioku capture` already no-op when the
 * cwd isn't a wired kioku repo (they check for the repo's state files), so a
 * global install is safe.
 *
 * All writes are idempotent: rerunning `init` upserts our entries in place and
 * never duplicates or clobbers unrelated config.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { homedir } from "node:os";
import { parse as parseToml, stringify as stringifyToml } from "smol-toml";
import {
  SUB_SESSION_START,
  SUB_STOP,
  cliInvocation,
  secondBrainSnippet,
  upsertMarkdownSnippet,
} from "./claude.js";

const MCP_SERVER_NAME = "kioku";

// SessionStart hook stdout is injected as context, but Codex caps a single
// additionalContext value at ~1000 tokens by default. kioku briefings are
// larger, so raise the per-hook limit generously (chars) to avoid truncating
// the injected briefing.
const SESSION_START_CONTEXT_LIMIT = 32000;

/** The global Codex config file. Honors CODEX_HOME (default ~/.codex). */
export function codexConfigPath(): string {
  const home = process.env.CODEX_HOME || join(homedir(), ".codex");
  return join(home, "config.toml");
}

type TomlTable = Record<string, unknown>;

/** Load + parse config.toml. Returns {} if it's missing, and backs up + resets
 *  if it exists but doesn't parse (mirrors claude.ts's tolerant loaders). */
function loadConfig(path: string): TomlTable {
  if (!existsSync(path)) return {};
  const raw = readFileSync(path, "utf8");
  try {
    return parseToml(raw) as TomlTable;
  } catch {
    writeFileSync(`${path}.backup`, raw);
    return {};
  }
}

function writeConfig(path: string, cfg: TomlTable): void {
  const dir = dirname(path);
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  writeFileSync(path, stringifyToml(cfg) + "\n");
}

// ── [mcp_servers.kioku] ───────────────────────────────────────────

/** Idempotently upsert the kioku MCP server as a streamable-HTTP entry:
 *
 *   [mcp_servers.kioku]
 *   url = "<url>"
 *   [mcp_servers.kioku.http_headers]
 *   Authorization = "Bearer <key>"
 *
 * The url comes straight from the minted MCP config, but rewritten to the
 * streamable-http path (/mcp) since kioku's SSE url ends in /sse and Codex only
 * speaks streamable HTTP. Preserves every other server + top-level key. */
export function writeCodexMcpConfig(serverEntry: {
  url: string;
  headers: Record<string, string>;
}): { path: string; existed: boolean } {
  const path = codexConfigPath();
  const existed = existsSync(path);
  const cfg = loadConfig(path);

  const servers = (cfg.mcp_servers as TomlTable | undefined) ?? {};
  servers[MCP_SERVER_NAME] = {
    url: toStreamableHttpUrl(serverEntry.url),
    http_headers: { ...serverEntry.headers },
  };
  cfg.mcp_servers = servers;

  writeConfig(path, cfg);
  return { path, existed };
}

/** kioku mints SSE urls (…/sse). Codex `url` is Streamable HTTP; the backend
 *  serves that at …/mcp. Rewrite a trailing /sse to /mcp; leave anything else
 *  alone (already /mcp, or a custom path). */
export function toStreamableHttpUrl(url: string): string {
  return url.replace(/\/sse\/?$/, "/mcp");
}

/** Read back the kioku MCP entry (url + plaintext key) from config.toml, for
 *  session-start's agent-neutral key/url resolution. */
export function readCodexMcpEntry(): {
  entry: { url: string; headers: Record<string, string> };
  key: string;
} | null {
  const path = codexConfigPath();
  if (!existsSync(path)) return null;
  let cfg: TomlTable;
  try {
    cfg = parseToml(readFileSync(path, "utf8")) as TomlTable;
  } catch {
    return null;
  }
  const server = (cfg.mcp_servers as TomlTable | undefined)?.[
    MCP_SERVER_NAME
  ] as { url?: string; http_headers?: Record<string, string> } | undefined;
  const url = server?.url;
  const auth = server?.http_headers?.["Authorization"];
  if (!url || !auth) return null;
  const key = auth.replace(/^Bearer\s+/, "");
  if (!key) return null;
  return { entry: { url, headers: server!.http_headers ?? {} }, key };
}

// ── [hooks.SessionStart] / [hooks.Stop] ───────────────────────────
//
// Codex hooks schema (HookEventsToml): a top-level `hooks` table whose event
// keys (SessionStart, Stop, …) are ARRAYS of matcher-groups, and each group's
// `hooks` key is an ARRAY of handlers. A command handler is
// { type = "command", command = "<cmd>" }. In TOML that's:
//
//   [[hooks.SessionStart]]
//   [[hooks.SessionStart.hooks]]
//   type = "command"
//   command = "<node> <entry> session-start"
//
// Verified to parse via `codex mcp list` / `codex doctor` (config.toml parse ok)
// against codex-cli 0.147.0. Hooks default to trustStatus=untrusted, so the
// FIRST launch passes --dangerously-bypass-hook-trust; interactive sessions
// afterward prompt the user once to trust the hook.

interface CommandHandler {
  type: "command";
  command: string;
  additionalContextLimit?: number;
}
interface MatcherGroup {
  matcher?: string;
  hooks: CommandHandler[];
}

/** Absolute `<node> <entry.js> <subcommand>` invocation, shared with claude.ts
 *  so hooks resolve without kioku on PATH (Codex runs hook commands via a
 *  shell that doesn't load the user's interactive PATH). */
function hookCommand(subcommand: string): string {
  return `${cliInvocation()} ${subcommand}`;
}

function isSubcommand(cmd: string | undefined, subcommand: string): boolean {
  return !!cmd && cmd.trim().endsWith(` ${subcommand}`);
}

/** Idempotently upsert a command hook for `event` → `<kioku> <subcommand>`.
 *  Strips any prior kioku group for the same subcommand (migrating a stale
 *  absolute path from an older node install) before adding the current one.
 *  Returns true if the config changed. */
function ensureCodexHook(
  cfg: TomlTable,
  event: "SessionStart" | "Stop",
  subcommand: string,
  extra?: Partial<CommandHandler>
): boolean {
  const hooks = (cfg.hooks as TomlTable | undefined) ?? {};
  const rawGroups = Array.isArray(hooks[event])
    ? (hooks[event] as MatcherGroup[])
    : [];

  const command = hookCommand(subcommand);
  let hadExact = false;
  let removedStale = false;

  // Drop any existing kioku handler for this subcommand from every group.
  for (const g of rawGroups) {
    if (!Array.isArray(g.hooks)) continue;
    const before = g.hooks.length;
    g.hooks = g.hooks.filter((h) => {
      if (h?.command === command) {
        hadExact = true;
        return true;
      }
      if (isSubcommand(h?.command, subcommand)) return false;
      return true;
    });
    if (g.hooks.length !== before) removedStale = true;
  }
  // Drop groups emptied by the strip.
  const kept = rawGroups.filter(
    (g) => Array.isArray(g.hooks) && g.hooks.length > 0
  );

  if (!hadExact) {
    kept.push({ hooks: [{ type: "command", command, ...extra }] });
  }

  hooks[event] = kept;
  cfg.hooks = hooks;
  return !hadExact || removedStale || kept.length !== rawGroups.length;
}

export function installCodexSessionStartHook(): {
  path: string;
  addedHook: boolean;
} {
  const path = codexConfigPath();
  const cfg = loadConfig(path);
  const changed = ensureCodexHook(cfg, "SessionStart", SUB_SESSION_START, {
    additionalContextLimit: SESSION_START_CONTEXT_LIMIT,
  });
  writeConfig(path, cfg);
  return { path, addedHook: changed };
}

export function installCodexStopHook(): { path: string; addedHook: boolean } {
  const path = codexConfigPath();
  const cfg = loadConfig(path);
  const changed = ensureCodexHook(cfg, "Stop", SUB_STOP);
  writeConfig(path, cfg);
  return { path, addedHook: changed };
}

// ── AGENTS.md ─────────────────────────────────────────────────────

/** Mirror updateClaudeMd into AGENTS.md (Codex's project-instructions file).
 *  Uses the no-push-hook snippet — the Codex surface wires only SessionStart +
 *  Stop, not a push activity-refresh hook. */
export function updateAgentsMd(repoRoot: string): {
  path: string;
  action: "created" | "appended" | "updated";
} {
  return upsertMarkdownSnippet(
    join(repoRoot, "AGENTS.md"),
    secondBrainSnippet({ pushHook: false })
  );
}
