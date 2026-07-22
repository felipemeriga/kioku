/**
 * Runs as a Claude Code PostToolUse hook scoped to the Bash tool. When the
 * Bash command that just ran was a `git push`, it nudges the SAME session to
 * refresh the repo's stored `activity` briefing from the newly-pushed commits
 * — using the session's own model/tokens (via the kioku MCP tools).
 *
 * The nudge is emitted as `hookSpecificOutput.additionalContext`, which Claude
 * Code injects into the model's context. Debounced on the last-synced commit
 * SHA in `.claude/kioku-state.json` so a push with no new commits is a no-op.
 *
 * Silent and best-effort — a git/parse hiccup never disrupts the session.
 * Always exits 0 and, unless there's a real nudge, prints nothing.
 */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  appendFileSync,
} from "node:fs";
import { join, resolve, dirname } from "node:path";
import { execSync, spawn } from "node:child_process";

interface HookPayload {
  session_id?: string;
  cwd?: string;
  tool_name?: string;
  tool_input?: { command?: string };
  // Claude Code has used both keys across versions.
  tool_output?: unknown;
  tool_response?: unknown;
}

interface StateFile {
  folder_id?: string;
  last_activity_sha?: string;
  last_activity_at?: string;
  [k: string]: unknown;
}

function statePath(repoRoot: string): string {
  return join(repoRoot, ".claude", "kioku-state.json");
}

function readState(repoRoot: string): StateFile {
  const p = statePath(repoRoot);
  if (!existsSync(p)) return {};
  try {
    return JSON.parse(readFileSync(p, "utf8")) as StateFile;
  } catch {
    return {};
  }
}

function writeState(repoRoot: string, next: StateFile): void {
  const p = statePath(repoRoot);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, JSON.stringify(next, null, 2) + "\n");
}

function logDebug(repoRoot: string, msg: string): void {
  if (!process.env.KIOKU_DEBUG) return;
  try {
    const p = join(repoRoot, ".claude", "kioku-onpush.log");
    mkdirSync(dirname(p), { recursive: true });
    appendFileSync(p, `[${new Date().toISOString()}] ${msg}\n`);
  } catch {
    // best-effort
  }
}

async function readStdinJson(): Promise<HookPayload> {
  return new Promise((resolvePromise) => {
    let raw = "";
    if (process.stdin.isTTY) {
      resolvePromise({});
      return;
    }
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (raw += chunk));
    process.stdin.on("end", () => {
      try {
        resolvePromise(raw ? (JSON.parse(raw) as HookPayload) : {});
      } catch {
        resolvePromise({});
      }
    });
    setTimeout(() => resolvePromise({}), 500);
  });
}

function git(cwd: string, args: string): string {
  return execSync(`git ${args}`, {
    cwd,
    stdio: ["ignore", "pipe", "ignore"],
    encoding: "utf8",
  }).trim();
}

function gitSafe(cwd: string, args: string): string {
  try {
    return git(cwd, args);
  } catch {
    return "";
  }
}

/** True when the command is (or contains) a `git push` invocation. Tolerates
 *  leading env vars, `&&` chains, and flags — but not the word "push" as an
 *  argument to something else. */
function isGitPush(command: string): boolean {
  return /(^|[;&|]\s*)git\s+(-[^\s]+\s+)*push\b/.test(command);
}

function buildInstruction(base: string | null, count: number): string {
  const range = base ? `${base}..HEAD` : "the recently pushed commits";
  const n =
    count > 0 ? `${count} new commit${count === 1 ? "" : "s"}` : "new work";
  return [
    `[kioku] A git push just landed ${n}. Refresh this repo's stored`,
    `\`activity\` briefing so the web UI stays current — do it now, briefly,`,
    `without pausing to ask.`,
    `1) Run \`git log ${range} --stat\` to see what changed.`,
    `2) Read the current activity via \`get_folder_briefing\`.`,
    `3) Merge the new work in: refresh the \`summary\` narrative and prepend`,
    `concise \`highlights\` bullets for the new commits (group related ones;`,
    `note PR numbers if visible). Keep existing highlights that still matter.`,
    `4) Save with \`update_folder_briefing_section(section="activity", pin=false,`,
    `content=<JSON {"summary": "...", "highlights": [...]}>)\`.`,
    `Only touch the activity section; don't regenerate the rest.`,
  ].join(" ");
}

function emit(additionalContext: string): void {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PostToolUse",
        additionalContext,
      },
    })
  );
}

/** Refresh the code graph in a detached background process so the push hook
 *  returns immediately. `kioku index` self-gates on last_indexed_sha and
 *  no-ops if graphify isn't installed. */
function spawnIndex(repoRoot: string): void {
  try {
    const child = spawn(process.execPath, [process.argv[1], "index"], {
      cwd: repoRoot,
      detached: true,
      stdio: "ignore",
    });
    child.unref();
  } catch {
    // best-effort — never disrupt the push
  }
}

export async function onPush(): Promise<void> {
  const payload = await readStdinJson();
  const repoRoot = resolve(payload.cwd || process.cwd());

  // Only act on Bash `git push` commands.
  const command = payload.tool_input?.command ?? "";
  if (payload.tool_name && payload.tool_name !== "Bash") return;
  if (!isGitPush(command)) return;

  // Opted-in repo only (has a wired kioku MCP entry).
  if (!existsSync(join(repoRoot, ".mcp.json"))) {
    logDebug(repoRoot, "no .mcp.json — skip");
    return;
  }

  // Refresh the code graph in the background (detached, non-blocking).
  spawnIndex(repoRoot);
  logDebug(repoRoot, "spawned detached `kioku index`");

  const head = gitSafe(repoRoot, "rev-parse HEAD");
  if (!head) {
    logDebug(repoRoot, "no HEAD — skip");
    return;
  }

  const state = readState(repoRoot);
  const base = state.last_activity_sha ?? null;

  // Debounce: if we've already covered up to HEAD, or there are no commits
  // since the last synced SHA, there's nothing to refresh.
  if (base === head) {
    logDebug(repoRoot, `already at ${head} — skip`);
    return;
  }
  let count = 0;
  if (base) {
    const c = gitSafe(repoRoot, `rev-list --count ${base}..HEAD`);
    count = parseInt(c, 10) || 0;
    if (count === 0) {
      logDebug(repoRoot, `no new commits since ${base} — skip`);
      return;
    }
  }

  emit(buildInstruction(base, count));

  // Optimistically advance the watermark so repeated pushes don't re-nudge for
  // the same commits. Best-effort: if the session ignores the nudge, the next
  // push simply covers the following delta.
  writeState(repoRoot, {
    ...state,
    last_activity_sha: head,
    last_activity_at: new Date().toISOString(),
  });
  logDebug(repoRoot, `nudged for ${base ?? "(init)"}..${head} (${count})`);
}
