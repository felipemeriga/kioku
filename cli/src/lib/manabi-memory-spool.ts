import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname } from "node:path";
import type { InventoryRepo } from "./manabi-inventory.js";
import {
  claudeMemorySource,
  type AgentMemorySource,
  type MemoryEvent,
} from "./manabi-memory-source.js";
import { codexMemorySource } from "./manabi-memory-codex.js";
import { discoverAgentMemoryFiles, readAgentMemoryFile } from "./manabi-memory-files.js";

interface State {
  initialized: boolean;
  offsets: Record<string, number>;
  pending: MemoryEvent[];
  blocked: string[];
  memoryHashes?: Record<string, string>;
}

const MAX_SPOOL_BYTES = 10 * 1024 * 1024;
const MAX_EVENTS = 1000;
const MAX_FRAME_BYTES = 64 * 1024;
const SOURCES: AgentMemorySource[] = [claudeMemorySource, codexMemorySource];

export class ManabiMemorySpool {
  private state: State;

  constructor(
    private path: string,
    private home: string
  ) {
    this.state = existsSync(path)
      ? (JSON.parse(readFileSync(path, "utf8")) as State)
      : { initialized: false, offsets: {}, pending: [], blocked: [] };
    if (
      !this.state ||
      typeof this.state.initialized !== "boolean" ||
      !this.state.offsets ||
      !Array.isArray(this.state.pending) ||
      !Array.isArray(this.state.blocked)
    )
      throw new Error("Invalid Manabi memory spool; repair it before restarting capture");
  }

  private save(): void {
    mkdirSync(dirname(this.path), { recursive: true, mode: 0o700 });
    const temporary = `${this.path}.${process.pid}.tmp`;
    writeFileSync(temporary, JSON.stringify(this.state), { mode: 0o600 });
    renameSync(temporary, this.path);
  }

  collect(repositories: InventoryRepo[]): "ok" | "full" | "oversized" {
    const sessions = SOURCES.flatMap((source) => source.discover(this.home, repositories)
      .map((session) => ({ ...session, adapter: source })));
    if (!this.state.initialized) {
      for (const { file } of sessions) this.state.offsets[file] = statSync(file).size;
      this.state.initialized = true;
      this.save();
      // Existing native memory files are imported; only old transcripts are skipped.
    }
    let result: "ok" | "full" | "oversized" = "ok";
    for (const session of sessions) {
      const { file, folderId } = session;
      const offset = this.state.offsets[file] ?? 0;
      const chunk = session.adapter.read(file, folderId, offset, 48 * 1024);
      if (chunk.oversized) {
        result = "oversized";
        continue;
      }
      if (chunk.events.length === 0 && chunk.nextOffset !== offset) {
        this.state.offsets[file] = chunk.nextOffset;
        this.save();
      }
      for (const event of chunk.events) {
        const encoded = JSON.stringify(event);
        if (
          Buffer.byteLength(encoded) > MAX_FRAME_BYTES ||
          this.state.pending.length >= MAX_EVENTS ||
          Buffer.byteLength(JSON.stringify(this.state)) + Buffer.byteLength(encoded) >
            MAX_SPOOL_BYTES
        ) {
          result = Buffer.byteLength(encoded) > MAX_FRAME_BYTES ? "oversized" : "full";
          break;
        }
        this.state.pending.push(event);
        this.state.offsets[file] =
          event.record_position + Buffer.byteLength(event.content) + 1;
        this.save();
      }
      if (result === "ok" && this.state.offsets[file] !== chunk.nextOffset) {
        this.state.offsets[file] = chunk.nextOffset;
        this.save();
      }
      if (result !== "ok") break;
    }
    if (result !== "ok") return result;
    this.state.memoryHashes ??= {};
    for (const item of discoverAgentMemoryFiles(this.home, repositories)) {
      try {
        const event = readAgentMemoryFile(item);
        const key = `${item.source}:${item.folderId}:${item.file}`;
        if (this.state.memoryHashes[key] === event.content_hash) continue;
        const encoded = JSON.stringify(event);
        if (Buffer.byteLength(encoded) > MAX_FRAME_BYTES) return "oversized";
        if (this.state.pending.length >= MAX_EVENTS ||
            Buffer.byteLength(JSON.stringify(this.state)) + Buffer.byteLength(encoded) > MAX_SPOOL_BYTES)
          return "full";
        this.state.pending.push(event);
        this.state.memoryHashes[key] = event.content_hash;
        this.save();
      } catch { /* A changing or unavailable file is retried on the next scan. */ }
    }
    return result;
  }

  next(): MemoryEvent | undefined {
    return this.state.pending.find(
      (event) => !this.state.blocked.includes(event.event_id)
    );
  }

  acknowledge(eventId: string): void {
    const before = this.state.pending.length;
    this.state.pending = this.state.pending.filter(
      (event) => event.event_id !== eventId
    );
    if (this.state.pending.length !== before) {
      this.state.blocked = this.state.blocked.filter((id) => id !== eventId);
      this.save();
    }
  }

  block(eventId: string): void {
    if (
      this.state.pending.some((event) => event.event_id === eventId) &&
      !this.state.blocked.includes(eventId)
    ) {
      this.state.blocked.push(eventId);
      this.save();
    }
  }

  pendingCount(): number {
    return this.state.pending.length;
  }
}
