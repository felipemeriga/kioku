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
import { discoverAgentMemoryFiles } from "./manabi-memory-files.js";
import { discoverCodexSessions, readCodexRecords } from "./manabi-memory-codex.js";
import { homedir } from "node:os";

function fixture() {
  const home = mkdtempSync(join(tmpdir(), "manabi-memory-"));
  const repoPath = join(home, "code", "project");
  mkdirSync(repoPath, { recursive: true });
  const project = join(
    home,
    ".claude",
    "projects",
    repoPath.replace(/[^A-Za-z0-9-]/g, "-")
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

test("Claude and Codex native memories share one event envelope", () => {
  const f = fixture();
  try {
    const claudeDir = join(f.file, "..", "memory");
    mkdirSync(claudeDir, { recursive: true });
    writeFileSync(join(claudeDir, "project.md"), "Known deployment preference");
    const codexDir = join(f.home, ".codex", "memories");
    const summaries = join(codexDir, "rollout_summaries");
    mkdirSync(summaries, { recursive: true });
    writeFileSync(join(summaries, "task.md"), "Known architecture decision");
    writeFileSync(join(codexDir, "MEMORY.md"),
      `- rollout_summaries/task.md (cwd=${f.repository.path}, rollout_path=/example, updated_at=2026-10-29)\n`);
    const repository = { ...f.repository, agents: ["claude", "codex"] as ("claude" | "codex")[] };
    const files = discoverAgentMemoryFiles(f.home, [repository]);
    assert.deepEqual(files.map((file) => file.source).sort(), ["claude_memory", "codex_memory"]);
    const spool = new ManabiMemorySpool(join(f.home, "memory-spool.json"), f.home);
    spool.collect([repository]);
    assert.equal(spool.pendingCount(), 2);
    const first = spool.next()!;
    assert.equal(first.provenance, "agent_memory");
    assert.equal(first.folder_id, repository.folder_id);
    spool.acknowledge(first.event_id);
    spool.collect([repository]);
    assert.equal(spool.pendingCount(), 1);
  } finally { rmSync(f.home, { recursive: true, force: true }); }
});

test("Codex adapter excludes developer, reasoning and tool records", () => {
  const f = fixture();
  try {
    const dir = join(f.home, ".codex", "sessions", "2026", "10", "29");
    mkdirSync(dir, { recursive: true });
    const file = join(dir, "rollout-test.jsonl");
    const line = (type: string, payload: object) => JSON.stringify({ timestamp: "2026-10-29T00:00:00Z", type, payload }) + "\n";
    writeFileSync(file, line("session_meta", { cwd: f.repository.path }) +
      line("response_item", { type: "message", role: "developer" }) +
      line("response_item", { type: "reasoning" }) +
      line("response_item", { type: "message", role: "user", content: [] }) +
      line("response_item", { type: "message", role: "assistant", content: [] }));
    const repository = { ...f.repository, agents: ["codex"] as ("claude" | "codex")[] };
    assert.equal(discoverCodexSessions(f.home, [repository]).length, 1);
    const result = readCodexRecords(file, repository.folder_id, 0);
    assert.deepEqual(result.events.map((event) => event.provenance), ["user", "assistant"]);
    assert.equal(result.events.every((event) => event.source === "codex"), true);
  } finally { rmSync(f.home, { recursive: true, force: true }); }
});

test("live local native memories traverse Manabi's WebSocket and ack", { skip: !process.env.KIOKU_LIVE_MEMORY_TEST }, async () => {
  const home = homedir();
  const repository: InventoryRepo = {
    id: "a".repeat(64), folder_id: "cccccccc-cccc-cccc-cccc-cccccccccccc",
    name: "kioku", path: "/Users/feliperamosdasilva/personal_projects/kioku",
    agents: ["claude", "codex"], initialized_at: new Date().toISOString(), available: true,
  };
  const files = discoverAgentMemoryFiles(home, [repository]);
  assert.ok(files.some((file) => file.source === "claude_memory"));
  assert.ok(files.some((file) => file.source === "codex_memory"));
  const root = mkdtempSync(join(tmpdir(), "kioku-live-memory-"));
  const server = new WebSocketServer({ port: 0, host: "127.0.0.1" });
  await new Promise<void>((resolve) => server.once("listening", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const controller = new AbortController();
  try {
    const spool = new ManabiMemorySpool(join(root, "spool.json"), home);
    assert.equal(spool.collect([repository]), "ok");
    assert.equal(spool.pendingCount(), files.length);
    const received: Record<string, number> = {};
    server.on("connection", (socket) => socket.on("message", (raw) => {
      const message = JSON.parse(raw.toString());
      if (message.type === "hello") socket.send(JSON.stringify({ type: "ready", capabilities: ["memory_post_v1"] }));
      if (message.type === "inventory") socket.send(JSON.stringify({ type: "inventory_ack", revision: message.revision }));
      if (message.type === "heartbeat") socket.send('{"type":"ack"}');
      if (message.type === "memory_post") {
        assert.equal(message.folder_id, repository.folder_id);
        received[message.source] = (received[message.source] || 0) + 1;
        socket.send(JSON.stringify({ type: "memory_ack", event_id: message.event_id }));
        if (Object.values(received).reduce((a, b) => a + b, 0) === files.length)
          setTimeout(() => controller.abort(), 50);
      }
    }));
    const deadline = setTimeout(() => controller.abort(), 5000);
    try {
      await runManabi({ signal: controller.signal,
        readConnection: () => ({ id: "machine", secret: "a".repeat(64), api_base: `http://127.0.0.1:${address.port}` }),
        snapshot: () => ({ repositories: [repository] }),
        memory: { collect: () => { spool.collect([repository]); }, next: () => spool.next(), acknowledge: (id) => spool.acknowledge(id), block: (id) => spool.block(id) },
        heartbeatMs: 20, timeoutMs: 500, delay: () => 1,
      });
    } finally { clearTimeout(deadline); }
    assert.equal(received.claude_memory, files.filter((file) => file.source === "claude_memory").length);
    assert.equal(received.codex_memory, files.filter((file) => file.source === "codex_memory").length);
    assert.equal(spool.pendingCount(), 0);
  } finally {
    controller.abort();
    for (const socket of server.clients) socket.terminate();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    rmSync(root, { recursive: true, force: true });
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
