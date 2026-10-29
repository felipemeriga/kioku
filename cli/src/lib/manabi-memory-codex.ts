import { createHash } from "node:crypto";
import { closeSync, existsSync, openSync, readSync, readdirSync, realpathSync, statSync } from "node:fs";
import { basename, join, sep } from "node:path";
import type { InventoryRepo } from "./manabi-inventory.js";
import type { AgentMemorySource, AgentSession, MemoryEvent } from "./manabi-memory-source.js";

const hash = (value: string) => createHash("sha256").update(value).digest("hex");

function sessionCwd(file: string): string | undefined {
  const handle = openSync(file, "r");
  try {
    const bytes = Buffer.alloc(64 * 1024);
    const count = readSync(handle, bytes, 0, bytes.length, 0);
    for (const line of bytes.subarray(0, count).toString("utf8").split("\n").slice(0, 10)) {
      try {
        const row = JSON.parse(line) as { type?: string; payload?: { cwd?: string } };
        if (row.type === "session_meta" && typeof row.payload?.cwd === "string")
          return realpathSync(row.payload.cwd);
      } catch { /* Partial metadata or unavailable working directory. */ }
    }
  } finally { closeSync(handle); }
  return undefined;
}

export function discoverCodexSessions(home: string, repositories: InventoryRepo[]): AgentSession[] {
  const roots = repositories.filter((repo) => repo.available && repo.agents.includes("codex"))
    .flatMap((repo) => {
      try { return [{ path: realpathSync(repo.path), folderId: repo.folder_id }]; }
      catch { return []; }
    });
  if (!roots.length) return [];
  const root = join(process.env.CODEX_HOME || join(home, ".codex"), "sessions");
  const sessions: AgentSession[] = [];
  let inspected = 0;
  try {
    for (const year of readdirSync(root).sort()) {
      if (!/^\d{4}$/.test(year)) continue;
      for (const month of readdirSync(join(root, year)).sort()) {
        if (!/^(0[1-9]|1[0-2])$/.test(month)) continue;
        for (const day of readdirSync(join(root, year, month)).sort()) {
          if (!/^\d{2}$/.test(day)) continue;
          for (const name of readdirSync(join(root, year, month, day))) {
            if (!/^rollout-.*\.jsonl$/.test(name)) continue;
            if (++inspected > 20_000) return sessions;
            const file = join(root, year, month, day, name);
            try {
              const cwd = sessionCwd(file);
              const binding = roots.find((repo) => cwd && (cwd === repo.path || cwd.startsWith(repo.path + sep)));
              if (binding) sessions.push({ file, folderId: binding.folderId, source: "codex" });
            } catch { /* An unreadable session does not block other sessions. */ }
          }
        }
      }
    }
  } catch { /* Codex has no sessions yet, or the tree is unavailable. */ }
  return sessions;
}

export function readCodexRecords(file: string, folderId: string, from: number, maxBytes = 64 * 1024): {
  events: MemoryEvent[]; nextOffset: number; oversized: boolean;
} {
  const size = statSync(file).size;
  const start = size < from ? 0 : from;
  const handle = openSync(file, "r");
  let bytes: Buffer;
  try {
    bytes = Buffer.alloc(Math.min(maxBytes, size - start));
    readSync(handle, bytes, 0, bytes.length, start);
  } finally { closeSync(handle); }
  const complete = bytes.lastIndexOf(10);
  if (complete < 0) return { events: [], nextOffset: start, oversized: size - start > maxBytes };
  const sessionId = basename(file, ".jsonl");
  const events: MemoryEvent[] = [];
  let position = start;
  for (const content of bytes.subarray(0, complete + 1).toString("utf8").split("\n")) {
    if (!content) { position += 1; continue; }
    try {
      const row = JSON.parse(content) as {
        type?: string; timestamp?: string;
        payload?: { type?: string; role?: string };
      };
      if (row.type === "response_item" && row.payload?.type === "message" &&
          (row.payload.role === "user" || row.payload.role === "assistant")) {
        const contentHash = hash(content);
        events.push({
          type: "memory_post", protocol: 1,
          event_id: hash(`codex\0${folderId}\0${sessionId}\0${position}\0${contentHash}`),
          content_hash: contentHash, folder_id: folderId, session_id: sessionId,
          source: "codex", source_schema_version: 1, record_position: position,
          event_time: typeof row.timestamp === "string" && Number.isFinite(Date.parse(row.timestamp))
            ? new Date(row.timestamp).toISOString() : null,
          observed_at: new Date().toISOString(), provenance: row.payload.role,
          sensitivity: "normal", content,
        });
      }
    } catch { /* Unknown or incomplete record remains non-authoritative. */ }
    position += Buffer.byteLength(content) + 1;
  }
  return { events, nextOffset: start + complete + 1, oversized: false };
}

export const codexMemorySource: AgentMemorySource = {
  source: "codex", discover: discoverCodexSessions, read: readCodexRecords,
};
