/** Local, agent-neutral Markdown journal. No transcript content is uploaded. */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { join, dirname } from "node:path";
import { hostname } from "node:os";

export type AgentName = "claude_code" | "codex";

export interface CapturedTurn {
  agent: AgentName;
  sessionId: string;
  turnId: string;
  user: string;
  assistant: string;
  sourcePath?: string;
}

export interface JournalEntry {
  id: string;
  agent: AgentName;
  session_id: string;
  turn_id: string;
  captured_at: string;
  source_ref: string;
  computer_name?: string;
  session_title?: string;
  session_summary?: string;
  schema: 1;
}

const MARKER_RE = /^<!-- kioku-entry: (\{[^\n]+\}) -->$/gm;
const SECRET_RE = /(Bearer\s+\S+|sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{16,}|mongodb(?:\+srv)?:\/\/\S+)/gi;
export function redactJournalText(text: string): string {
  return text.replace(SECRET_RE, "[redacted]");
}

function messageText(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((part) => part && typeof part === "object" && ["text", "input_text", "output_text"].includes((part as { type?: string }).type ?? ""))
    .map((part) => String((part as { text?: unknown }).text ?? ""))
    .join("\n");
}

/** Extract only the latest real user turn and assistant prose from JSONL. */
export function parseTurn(
  agent: AgentName,
  payload: Record<string, unknown>,
): CapturedTurn | null {
  const sourcePath = typeof payload.transcript_path === "string" ? payload.transcript_path : undefined;
  const lines = sourcePath && existsSync(sourcePath)
    ? readFileSync(sourcePath, "utf8").split("\n")
    : [];
  let sessionId = typeof payload.session_id === "string" ? payload.session_id : "";
  const events: Array<{ line: number; user?: string; assistant?: string; id?: string }> = [];
  for (let i = 0; i < lines.length; i++) {
    let obj: Record<string, unknown>;
    try { obj = JSON.parse(lines[i]) as Record<string, unknown>; } catch { continue; }
    if (!sessionId && typeof obj.sessionId === "string") sessionId = obj.sessionId;
    if (agent === "claude_code") {
      const message = obj.message as { content?: unknown } | undefined;
      if (obj.type === "user" && !obj.isMeta) {
        const user = messageText(message?.content).trim();
        if (user) events.push({ line: i, user, id: String(obj.uuid ?? i) });
      } else if (obj.type === "assistant") {
        const assistant = messageText(message?.content).trim();
        if (assistant) events.push({ line: i, assistant });
      }
    } else {
      const data = obj.payload as Record<string, unknown> | undefined;
      const item = data?.item as { type?: string; id?: string; content?: unknown } | undefined;
      if (obj.type === "event_msg" && data?.type === "user_message") {
        const user = String(data.message ?? "").trim();
        if (user) events.push({ line: i, user, id: String(data.id ?? i) });
      } else if (obj.type === "event_msg" && data?.type === "agent_message") {
        const assistant = String(data.message ?? "").trim();
        if (assistant) events.push({ line: i, assistant });
      } else if (obj.type === "event_msg" && data?.type === "item_completed" && item?.type === "UserMessage") {
        const user = messageText(item.content).trim();
        if (user) events.push({ line: i, user, id: String(item.id ?? i) });
      } else if (obj.type === "event_msg" && data?.type === "item_completed" && item?.type === "AgentMessage") {
        const assistant = messageText(item.content).trim();
        if (assistant) events.push({ line: i, assistant });
      } else if (obj.type === "response_item" && data?.type === "message" && data.role === "assistant") {
        const assistant = messageText(data.content).trim();
        if (assistant) events.push({ line: i, assistant });
      }
    }
  }
  let start = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].user) { start = i; break; }
  }
  if (start < 0) return null;
  const first = events[start];
  const final = typeof payload.last_assistant_message === "string"
    ? payload.last_assistant_message.trim()
    : "";
  const assistant = final || events.slice(start + 1)
    .filter((event) => event.assistant)
    .map((event) => event.assistant)
    .join("\n");
  if (!assistant || !sessionId) return null;
  const turnId = String(first.id ?? first.line);
  return {
    agent, sessionId, turnId,
    user: first.user!.slice(0, 5000),
    assistant: assistant.slice(-12000),
    sourcePath,
  };
}

export function localDateTime(now = new Date()): { day: string; timestamp: string } {
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const offset = -now.getTimezoneOffset();
  const tz = `${offset >= 0 ? "+" : "-"}${pad(Math.floor(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`;
  return {
    day,
    timestamp: `${day}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}${tz}`,
  };
}

export function journalDir(repoRoot: string): string {
  return join(repoRoot, ".kioku", "memory");
}

export function journalPath(repoRoot: string, day: string): string {
  return join(journalDir(repoRoot), `${day}.md`);
}

export function journalHeader(day: string): string {
  return `# Kioku agent journal — ${day}\n\n`;
}

export function normalizeBullets(output: string): string {
  const text = output.trim().replace(/^```(?:markdown)?\s*\n|\n```\s*$/g, "");
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length < 2 || lines.length > 10 || lines.some((line) => !line.startsWith("- ")))
    throw new Error("Summarizer must return 2–10 Markdown bullets");
  return redactJournalText(lines.join("\n"));
}

export function renderEntry(turn: CapturedTurn, bullets: string, timestamp: string, session?: { title: string; summary: string }): string {
  const id = `${turn.agent}:${turn.sessionId}:${turn.turnId}`;
  const metadata: JournalEntry = {
    id, agent: turn.agent, session_id: turn.sessionId, turn_id: turn.turnId,
    captured_at: timestamp, source_ref: `${turn.agent}://${turn.sessionId}/${turn.turnId}`, schema: 1,
    computer_name: hostname().slice(0, 120),
    ...(session ? { session_title: session.title, session_summary: session.summary } : {}),
  };
  const label = turn.agent === "claude_code" ? "Claude Code" : "Codex";
  return `## ${timestamp.slice(11, 16)} — ${label}\n<!-- kioku-entry: ${JSON.stringify(metadata)} -->\n\n${bullets}\n\n`;
}

export function parseJournal(markdown: string): Array<{ metadata: JournalEntry; block: string }> {
  const matches = [...markdown.matchAll(MARKER_RE)];
  const entries: Array<{ metadata: JournalEntry; block: string }> = [];
  for (let i = 0; i < matches.length; i++) {
    const marker = matches[i];
    const headingStart = markdown.lastIndexOf("\n## ", marker.index) + 1;
    const end = i + 1 < matches.length
      ? markdown.lastIndexOf("\n## ", matches[i + 1].index) + 1
      : markdown.length;
    entries.push({
      metadata: JSON.parse(marker[1]) as JournalEntry,
      block: markdown.slice(headingStart, end).trimEnd() + "\n\n",
    });
  }
  return entries;
}

export function mergeJournals(day: string, remote: string, local: string): string {
  const entries = new Map<string, { metadata: JournalEntry; block: string }>();
  for (const entry of [...parseJournal(local), ...parseJournal(remote)])
    entries.set(entry.metadata.id, entry);
  return journalHeader(day) + [...entries.values()]
    .sort((a, b) => a.metadata.captured_at.localeCompare(b.metadata.captured_at) || a.metadata.id.localeCompare(b.metadata.id))
    .map((entry) => entry.block)
    .join("");
}

export function sha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

export async function withJournalLock<T>(path: string, work: () => T | Promise<T>): Promise<T> {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const lock = `${path}.lock`;
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      mkdirSync(lock);
      try { return await work(); } finally { rmSync(lock, { recursive: true, force: true }); }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      try {
        if (Date.now() - statSync(lock).mtimeMs > 60_000)
          rmSync(lock, { recursive: true, force: true });
      } catch { /* another process may have released it */ }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  throw new Error("Timed out waiting for journal lock");
}

export function writeJournalAtomic(path: string, markdown: string): void {
  const temporary = `${path}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
  writeFileSync(temporary, markdown, { mode: 0o600 });
  renameSync(temporary, path);
}

export function listJournalDays(repoRoot: string): string[] {
  const dir = journalDir(repoRoot);
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((name) => /^\d{4}-\d{2}-\d{2}\.md$/.test(name))
    .map((name) => name.slice(0, -3));
}
