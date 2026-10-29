import { createHash } from "node:crypto";
import {
  closeSync,
  existsSync,
  openSync,
  readSync,
  readdirSync,
  realpathSync,
  statSync,
} from "node:fs";
import { basename, join } from "node:path";
import type { InventoryRepo } from "./manabi-inventory.js";

export interface MemoryEvent {
  type: "memory_post";
  protocol: 1;
  event_id: string;
  content_hash: string;
  folder_id: string;
  session_id: string;
  source: string;
  source_schema_version: number;
  record_position: number;
  event_time: string | null;
  observed_at: string;
  provenance: "user" | "assistant" | "tool_result" | "external_text" | "agent_memory" | "unknown";
  sensitivity: "normal";
  content: string;
}

const hash = (value: string) => createHash("sha256").update(value).digest("hex");

export interface AgentSession {
  file: string;
  folderId: string;
  source: MemoryEvent["source"];
}

export interface AgentMemorySource {
  source: MemoryEvent["source"];
  discover(home: string, repositories: InventoryRepo[]): AgentSession[];
  read(file: string, folderId: string, from: number, maxBytes?: number): {
    events: MemoryEvent[];
    nextOffset: number;
    oversized: boolean;
  };
}

function projectDirectory(home: string, path: string): string {
  return join(home, ".claude", "projects", path.replace(/[^A-Za-z0-9-]/g, "-"));
}

function belongsToRepo(file: string, repoPath: string): boolean {
  const handle = openSync(file, "r");
  try {
    const bytes = Buffer.alloc(64 * 1024);
    const count = readSync(handle, bytes, 0, bytes.length, 0);
    const text = bytes.subarray(0, count).toString("utf8");
    for (const line of text.split("\n").slice(0, 100)) {
      try {
        const value = JSON.parse(line) as { cwd?: unknown };
        if (typeof value.cwd === "string") {
          return existsSync(value.cwd) && realpathSync(value.cwd) === repoPath;
        }
      } catch {
        /* Partial or unknown line: inspect the next one. */
      }
    }
    return false;
  } finally {
    closeSync(handle);
  }
}

export function discoverClaudeSessions(
  home: string,
  repositories: InventoryRepo[]
): { file: string; folderId: string }[] {
  const sessions: { file: string; folderId: string }[] = [];
  for (const repo of repositories) {
    if (!repo.available || !repo.agents.includes("claude")) continue;
    try {
      const canonical = realpathSync(repo.path);
      for (const dir of new Set([
        projectDirectory(home, repo.path),
        projectDirectory(home, canonical),
      ])) {
        try {
          for (const name of readdirSync(dir)) {
            if (!/^[0-9a-f-]{36}\.jsonl$/i.test(name)) continue;
            const file = join(dir, name);
            if (belongsToRepo(file, canonical))
              sessions.push({ file, folderId: repo.folder_id });
          }
        } catch {
          /* One alias may not exist. */
        }
      }
    } catch {
      /* Missing project folder or unreadable session: retry next scan. */
    }
  }
  return sessions;
}

function provenance(value: unknown): MemoryEvent["provenance"] {
  if (!value || typeof value !== "object") return "unknown";
  const row = value as { type?: string; message?: { content?: unknown } };
  if (row.type === "assistant") return "assistant";
  if (row.type === "user") {
    if (
      Array.isArray(row.message?.content) &&
      row.message.content.some(
        (part) => part && typeof part === "object" && part.type === "tool_result"
      )
    )
      return "tool_result";
    return "user";
  }
  return row.type === "tool_result" ? "tool_result" : "unknown";
}

export function readClaudeRecords(
  file: string,
  folderId: string,
  from: number,
  maxBytes = 64 * 1024
): { events: MemoryEvent[]; nextOffset: number; oversized: boolean } {
  const size = statSync(file).size;
  const start = size < from ? 0 : from;
  const handle = openSync(file, "r");
  let bytes: Buffer;
  try {
    bytes = Buffer.alloc(Math.min(maxBytes, size - start));
    readSync(handle, bytes, 0, bytes.length, start);
  } finally {
    closeSync(handle);
  }
  const complete = bytes.lastIndexOf(10);
  if (complete < 0)
    return {
      events: [],
      nextOffset: start,
      oversized: size - start > maxBytes,
    };
  const sessionId = basename(file, ".jsonl");
  const events: MemoryEvent[] = [];
  let position = start;
  for (const lineBytes of bytes.subarray(0, complete + 1).toString("utf8").split("\n")) {
    if (!lineBytes) {
      position += 1;
      continue;
    }
    const content = lineBytes;
    const contentHash = hash(content);
    let row: unknown;
    try {
      row = JSON.parse(content);
    } catch {
      row = null;
    }
    const timestamp =
      row && typeof row === "object" && "timestamp" in row
        ? (row as { timestamp: unknown }).timestamp
        : null;
    const eventTime =
      typeof timestamp === "string" && Number.isFinite(Date.parse(timestamp))
        ? new Date(timestamp).toISOString()
        : null;
    events.push({
      type: "memory_post",
      protocol: 1,
      event_id: hash(`claude_code\0${folderId}\0${sessionId}\0${position}\0${contentHash}`),
      content_hash: contentHash,
      folder_id: folderId,
      session_id: sessionId,
      source: "claude_code",
      source_schema_version: 1,
      record_position: position,
      event_time: eventTime,
      observed_at: new Date().toISOString(),
      provenance: provenance(row),
      sensitivity: "normal",
      content,
    });
    position += Buffer.byteLength(content) + 1;
  }
  return { events, nextOffset: start + complete + 1, oversized: false };
}

export const claudeMemorySource: AgentMemorySource = {
  source: "claude_code",
  discover: (home, repositories) => discoverClaudeSessions(home, repositories).map(
    (session) => ({ ...session, source: "claude_code" })
  ),
  read: readClaudeRecords,
};
