/**
 * Runs as a Claude Code Stop hook. Every 10 minutes OR every 5 assistant
 * turns (whichever first), captures the transcript delta since the last
 * capture and ships it to /api/cli/session-capture, which distills 0-3
 * memories via Haiku and saves them to Mem0.
 *
 * Silent by default (writes to a rotating log file) so a hook error
 * never annoys the coding session. Always exits 0.
 */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  appendFileSync,
} from "node:fs";
import { join, resolve, dirname } from "node:path";

const MIN_TIME_BETWEEN_CAPTURES_MS = 10 * 60 * 1000; // 10 minutes
const MIN_TURNS_BETWEEN_CAPTURES = 5;

interface HookPayload {
  session_id?: string;
  transcript_path?: string;
  cwd?: string;
  stop_hook_active?: boolean;
}

interface StateFile {
  folder_id: string;
  folder_name?: string;
  scope_root_name?: string;
  last_capture_at?: string; // ISO
  last_capture_transcript_length?: number; // # of turns
  last_session_id?: string;
}

interface TranscriptTurn {
  role: "user" | "assistant";
  content: string;
  ts?: string;
}

function statePath(repoRoot: string): string {
  return join(repoRoot, ".claude", "agentic-rag-state.json");
}

function readState(repoRoot: string): StateFile | null {
  const p = statePath(repoRoot);
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, "utf8")) as StateFile;
  } catch {
    return null;
  }
}

function writeState(repoRoot: string, state: StateFile): void {
  const p = statePath(repoRoot);
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(p, JSON.stringify(state, null, 2) + "\n");
}

function logDebug(repoRoot: string, msg: string): void {
  if (!process.env.AGENTIC_RAG_DEBUG) return;
  try {
    const p = join(repoRoot, ".claude", "agentic-rag-capture.log");
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
    // Safety timeout — if Claude Code doesn't send stdin, exit gracefully.
    setTimeout(() => resolvePromise({}), 500);
  });
}

/** Parse Claude Code's JSONL transcript into a compact turn list. */
function parseTranscript(path: string): TranscriptTurn[] {
  if (!existsSync(path)) return [];
  try {
    const lines = readFileSync(path, "utf8").split("\n").filter((l) => l.trim());
    const turns: TranscriptTurn[] = [];
    for (const line of lines) {
      try {
        const obj = JSON.parse(line) as {
          type?: string;
          role?: string;
          message?: { role?: string; content?: unknown };
          timestamp?: string;
        };
        // Claude Code writes both {type:'user'/'assistant', message:{content:[...]}}
        // and simpler {role, content} shapes across versions. Normalize both.
        const role = obj.type ?? obj.role ?? obj.message?.role;
        if (role !== "user" && role !== "assistant") continue;
        const contentField = obj.message?.content ?? (obj as { content?: unknown }).content;
        const content = contentToText(contentField);
        if (!content) continue;
        turns.push({ role, content, ts: obj.timestamp });
      } catch {
        // skip bad lines
      }
    }
    return turns;
  } catch {
    return [];
  }
}

function contentToText(c: unknown): string {
  if (typeof c === "string") return c;
  if (Array.isArray(c)) {
    // Anthropic content blocks
    return c
      .map((block) => {
        if (typeof block === "string") return block;
        const b = block as { type?: string; text?: string; content?: unknown };
        if (b.type === "text" && typeof b.text === "string") return b.text;
        if (b.type === "tool_use") return `[tool_use ${(b as { name?: string }).name ?? ""}]`;
        if (b.type === "tool_result") {
          const tr = b as { content?: unknown };
          const inner = typeof tr.content === "string"
            ? tr.content.slice(0, 500)
            : "";
          return `[tool_result ${inner}]`;
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  return "";
}

function readMcpApiKey(repoRoot: string): { key: string; sseUrl: string } | null {
  const path = join(repoRoot, ".mcp.json");
  if (!existsSync(path)) return null;
  try {
    const cfg = JSON.parse(readFileSync(path, "utf8")) as {
      mcpServers?: Record<
        string,
        { url?: string; headers?: Record<string, string> }
      >;
    };
    const entry = cfg.mcpServers?.["agentic-rag"];
    if (!entry?.headers?.Authorization || !entry.url) return null;
    return {
      key: entry.headers.Authorization.replace(/^Bearer\s+/, ""),
      sseUrl: entry.url,
    };
  } catch {
    return null;
  }
}

export async function capture(): Promise<void> {
  const cwd = resolve(process.cwd());
  const hook = await readStdinJson();
  if (hook.stop_hook_active) {
    // Prevent recursive hook trigger — Claude Code marks re-entrant calls.
    return;
  }

  const state = readState(cwd);
  if (!state) {
    logDebug(cwd, "no state file — this repo hasn't been init'd");
    return;
  }

  const mcp = readMcpApiKey(cwd);
  if (!mcp) {
    logDebug(cwd, "no .mcp.json — skipping");
    return;
  }

  // Derive REST base from SSE URL (same host, port 8001 → 8000 in dev).
  const base = new URL(mcp.sseUrl).origin.replace(/:8001$/, ":8000");

  const transcriptPath = hook.transcript_path;
  if (!transcriptPath) {
    logDebug(cwd, "no transcript_path in hook payload");
    return;
  }

  const allTurns = parseTranscript(transcriptPath);
  const lastLen = state.last_capture_transcript_length ?? 0;
  const delta = allTurns.slice(lastLen);
  if (delta.length === 0) {
    logDebug(cwd, "no new turns since last capture");
    return;
  }

  // Threshold check. On the FIRST-ever capture (no prior last_capture_at),
  // we only require the turn threshold — otherwise every fresh state file
  // trips the time check on turn 1 because `elapsed` computes to
  // ~epoch-ms and always exceeds 10min. After the first fire, both time
  // and turn thresholds are eligible triggers.
  const now = Date.now();
  const enoughTurns = delta.length >= MIN_TURNS_BETWEEN_CAPTURES;
  const isFirstCapture = !state.last_capture_at;
  const elapsed = isFirstCapture
    ? 0
    : now - Date.parse(state.last_capture_at!);
  const enoughTime =
    !isFirstCapture && elapsed >= MIN_TIME_BETWEEN_CAPTURES_MS;

  if (!enoughTime && !enoughTurns) {
    logDebug(
      cwd,
      `threshold not met (first=${isFirstCapture}, elapsed=${elapsed}ms, turns=${delta.length})`,
    );
    return;
  }

  logDebug(
    cwd,
    `firing capture: ${delta.length} turns, ${elapsed}ms since last`,
  );

  try {
    const res = await fetch(`${base}/api/cli/session-capture`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${mcp.key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        folder_id: state.folder_id,
        session_id: hook.session_id ?? "unknown",
        cwd: hook.cwd ?? cwd,
        transcript_delta: delta.map((t) => ({
          role: t.role,
          content: t.content,
          ts: t.ts,
        })),
      }),
    });
    if (!res.ok) {
      logDebug(cwd, `POST session-capture failed: ${res.status} ${await res.text()}`);
      return;
    }
    const body = (await res.json()) as { ok?: boolean; count?: number; skipped?: boolean };
    logDebug(cwd, `saved ${body.count ?? 0} memor${(body.count ?? 0) === 1 ? "y" : "ies"}`);

    // Update state
    writeState(cwd, {
      ...state,
      last_capture_at: new Date().toISOString(),
      last_capture_transcript_length: allTurns.length,
      last_session_id: hook.session_id ?? state.last_session_id,
    });
  } catch (err) {
    logDebug(cwd, `capture error: ${err instanceof Error ? err.message : String(err)}`);
    // Silent — never fail a hook
  }
}
