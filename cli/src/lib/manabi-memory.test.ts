import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  appendFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import type { InventoryRepo } from "./manabi-inventory.js";
import { discoverClaudeSessions, readClaudeRecords } from "./manabi-memory-source.js";
import { ManabiMemorySpool } from "./manabi-memory-spool.js";
import { runManabi } from "./manabi-client.js";
import { WebSocketServer } from "ws";

function fixture() {
  const home = mkdtempSync(join(tmpdir(), "manabi-memory-"));
  const repoPath = join(home, "code", "project");
  mkdirSync(repoPath, { recursive: true });
  const project = join(
    home,
    ".claude",
    "projects",
    repoPath.replace(/[\\/]/g, "-")
  );
  mkdirSync(project, { recursive: true });
  const file = join(project, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.jsonl");
  const row = (type: string, text: string) =>
    JSON.stringify({ cwd: repoPath, type, message: { content: text }, timestamp: "2026-10-29T00:00:00Z" }) +
    "\n";
  const repository: InventoryRepo = {
    id: "b".repeat(64),
    folder_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
    name: "project",
    path: repoPath,
    agents: ["claude"],
    initialized_at: "2026-10-29T00:00:00Z",
    available: true,
  };
  return { home, file, repository, row };
}

test("only bound Claude projects are discovered", () => {
  const f = fixture();
  try {
    writeFileSync(f.file, f.row("user", "first"));
    assert.equal(discoverClaudeSessions(f.home, [f.repository]).length, 1);
    assert.equal(
      discoverClaudeSessions(f.home, [{ ...f.repository, agents: ["codex"] }]).length,
      0
    );
    assert.equal(
      discoverClaudeSessions(f.home, [{ ...f.repository, folder_id: "d".repeat(36), path: f.home }])
        .length,
      0
    );
  } finally {
    rmSync(f.home, { recursive: true, force: true });
  }
});

test("complete JSONL records have stable IDs and incomplete lines stay unread", () => {
  const f = fixture();
  try {
    const line = f.row("user", "new fact");
    writeFileSync(f.file, line + '{"type":"assistant"');
    const first = readClaudeRecords(f.file, f.repository.folder_id, 0);
    const again = readClaudeRecords(f.file, f.repository.folder_id, 0);
    assert.equal(first.events.length, 1);
    assert.equal(first.events[0].event_id, again.events[0].event_id);
    assert.equal(first.events[0].content_hash, createHash("sha256").update(line.trim()).digest("hex"));
    assert.equal(first.nextOffset, Buffer.byteLength(line));
    appendFileSync(f.file, "}\n");
    assert.equal(readClaudeRecords(f.file, f.repository.folder_id, first.nextOffset).events.length, 1);
  } finally {
    rmSync(f.home, { recursive: true, force: true });
  }
});

test("spool skips old history, persists new events, replays and acknowledges", () => {
  const f = fixture();
  try {
    writeFileSync(f.file, f.row("user", "old"));
    const path = join(f.home, "spool.json");
    const spool = new ManabiMemorySpool(path, f.home);
    assert.equal(spool.collect([f.repository]), "ok");
    assert.equal(spool.pendingCount(), 0);
    appendFileSync(f.file, f.row("user", "new"));
    assert.equal(spool.collect([f.repository]), "ok");
    assert.equal(spool.pendingCount(), 1);
    const replay = new ManabiMemorySpool(path, f.home);
    assert.equal(replay.next()?.content.includes("new"), true);
    const id = replay.next()!.event_id;
    replay.block(id);
    assert.equal(replay.next(), undefined);
    replay.acknowledge(id);
    assert.equal(new ManabiMemorySpool(path, f.home).pendingCount(), 0);
    assert.equal(JSON.parse(readFileSync(path, "utf8")).pending.length, 0);
  } finally {
    rmSync(f.home, { recursive: true, force: true });
  }
});

test("unacknowledged memory replays with the same ID after reconnect", async () => {
  const f = fixture();
  const server = new WebSocketServer({ port: 0, host: "127.0.0.1" });
  await new Promise<void>((resolve) => server.once("listening", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const controller = new AbortController();
  const spool = new ManabiMemorySpool(join(f.home, "spool.json"), f.home);
  try {
    spool.collect([f.repository]);
    appendFileSync(f.file, f.row("user", "new"));
    const received: string[] = [];
    server.on("connection", (socket) => socket.on("message", (raw) => {
      const message = JSON.parse(raw.toString());
      if (message.type === "hello") socket.send(JSON.stringify({ type: "ready", capabilities: ["memory_post_v1"] }));
      if (message.type === "inventory") socket.send(JSON.stringify({ type: "inventory_ack", revision: message.revision }));
      if (message.type === "heartbeat") socket.send('{"type":"ack"}');
      if (message.type === "memory_post") {
        received.push(message.event_id);
        if (received.length === 1) socket.terminate();
        else { socket.send(JSON.stringify({ type: "memory_ack", event_id: message.event_id })); setTimeout(() => controller.abort(), 30); }
      }
    }));
    const deadline = setTimeout(() => controller.abort(), 3000);
    try {
      await runManabi({
        signal: controller.signal,
        readConnection: () => ({ id: "machine", secret: "a".repeat(64), api_base: `http://127.0.0.1:${address.port}` }),
        snapshot: () => ({ repositories: [f.repository] }),
        memory: { collect: () => { spool.collect([f.repository]); }, next: () => spool.next(), acknowledge: (id) => spool.acknowledge(id), block: (id) => spool.block(id) },
        heartbeatMs: 20, timeoutMs: 500, delay: () => 1,
      });
      assert.equal(received.length, 2);
      assert.equal(received[0], received[1]);
      assert.equal(spool.pendingCount(), 0);
    } finally { clearTimeout(deadline); }
  } finally {
    controller.abort();
    for (const socket of server.clients) socket.terminate();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    rmSync(f.home, { recursive: true, force: true });
  }
});
