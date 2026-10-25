import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  symlinkSync,
  readFileSync,
  rmSync,
  realpathSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WebSocketServer } from "ws";
import {
  runManabi,
  reconnectDelay,
  ManabiDiagnostics,
} from "./manabi-client.js";
import { manabiNodeExecutable } from "./manabi.js";

test(
  "Node service preserves stable package-manager link across version replacement",
  { skip: process.platform === "win32" },
  () => {
    const root = mkdtempSync(join(tmpdir(), "manabi-node-"));
    try {
      mkdirSync(join(root, "bin"));
      const old = join(root, "node-v1");
      const replacement = join(root, "node-v2");
      const stable = join(root, "bin/node");
      writeFileSync(old, "old");
      writeFileSync(replacement, "new");
      symlinkSync(old, stable);
      const executable = manabiNodeExecutable(old, join(root, "bin"), "darwin");
      assert.equal(executable, stable);
      rmSync(stable);
      symlinkSync(replacement, stable);
      rmSync(old);
      assert.equal(readFileSync(executable, "utf8"), "new");
      assert.equal(
        manabiNodeExecutable(replacement, "relative/path", "darwin"),
        realpathSync(replacement)
      );
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  }
);

test("diagnostics retain only 50 sanitized transitions, survive restart and never block on disk failure", () => {
  const root = mkdtempSync(join(tmpdir(), "manabi-diagnostics-"));
  try {
    const path = join(root, "connection.json");
    const diagnostics = new ManabiDiagnostics(path);
    for (let i = 0; i < 1000; i++)
      diagnostics.record(i % 2 ? "connected" : "connection_unavailable");
    diagnostics.record("connected");
    diagnostics.record("secret=not-allowed");
    const events = JSON.parse(
      readFileSync(join(root, "diagnostics.json"), "utf8")
    );
    assert.equal(events.length, 50);
    assert.ok(
      events.every(
        (event: object) => Object.keys(event).join() === "code,observed_at"
      )
    );
    new ManabiDiagnostics(path).record("signed_out");
    assert.equal(
      JSON.parse(readFileSync(join(root, "diagnostics.json"), "utf8")).at(-1)
        .code,
      "signed_out"
    );
    new ManabiDiagnostics(join(root, "absent", "config")).record("connected");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

for (const fault of ["clock_backwards", "suspension", "half_open"] as const) {
  test(`${fault}: a real socket reconnects and preserves at most one active connection`, async () => {
    const server = new WebSocketServer({ port: 0, host: "127.0.0.1" });
    await new Promise<void>((resolve) => server.once("listening", resolve));
    const address = server.address();
    assert.ok(address && typeof address !== "string");
    const config = {
      id: "machine",
      secret: "a".repeat(64),
      api_base: `http://127.0.0.1:${address.port}`,
    };
    const controller = new AbortController();
    let connections = 0;
    let offset = 0;
    let monoOffset = 0;
    server.on("connection", (socket) => {
      connections++;
      socket.on("message", (raw) => {
        const message = JSON.parse(raw.toString());
        if (message.type === "hello") {
          socket.send('{"type":"ready"}');
          if (connections === 1)
            setTimeout(() => {
              if (fault === "clock_backwards") offset = -7 * 86400000;
              if (fault === "suspension") {
                offset = 7 * 86400000;
                monoOffset = 7 * 86400000;
              }
            }, 10);
          else controller.abort();
        } else if (fault !== "half_open") socket.send('{"type":"ack"}');
      });
    });
    const deadline = setTimeout(() => controller.abort(), 2000);
    try {
      await runManabi({
        signal: controller.signal,
        readConnection: () => config,
        heartbeatMs: 5,
        timeoutMs: 40,
        delay: () => 1,
        wallNow: () => Date.now() + offset,
        monotonicNow: () => performance.now() + monoOffset,
      });
      assert.equal(connections, 2);
    } finally {
      clearTimeout(deadline);
      for (const c of server.clients) c.terminate();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
}

test("simulated month has capped jitter and missing credentials keep retrying until aborted", async () => {
  let elapsed = 0;
  let attempts = 0;
  // Accelerated policy simulation, not a claim of a month-long physical run.
  while (elapsed < 31 * 86400000) {
    const delay = reconnectDelay(Math.min(attempts, 6), () => attempts % 2);
    assert.ok(delay >= 500 && delay <= 60000);
    elapsed += delay;
    attempts++;
  }
  assert.ok(attempts > 40000);
  const controller = new AbortController();
  let reads = 0;
  await runManabi({
    signal: controller.signal,
    readConnection: () => {
      reads++;
      return null;
    },
    delay: () => {
      if (reads === 100) controller.abort();
      return 1;
    },
  });
  assert.equal(reads, 100);
});

test("100 real reconnects release sockets/listeners and keep memory bounded", async () => {
  const server = new WebSocketServer({ port: 0, host: "127.0.0.1" });
  await new Promise<void>((resolve) => server.once("listening", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const controller = new AbortController();
  const rss = process.memoryUsage().rss;
  let total = 0;
  let peakSockets = 0;
  server.on("connection", (socket) => {
    total++;
    peakSockets = Math.max(peakSockets, server.clients.size);
    socket.once("message", () => {
      if (total === 100) controller.abort();
      else socket.terminate();
    });
  });
  const deadline = setTimeout(() => controller.abort(), 5000);
  try {
    await runManabi({
      signal: controller.signal,
      readConnection: () => ({
        id: "machine",
        secret: "a".repeat(64),
        api_base: `http://127.0.0.1:${address.port}`,
      }),
      delay: () => 1,
    });
    assert.equal(total, 100);
    assert.equal(peakSockets, 1);
    assert.ok(process.memoryUsage().rss - rss < 64 * 1024 * 1024);
  } finally {
    clearTimeout(deadline);
    const closed = [...server.clients].map(
      (socket) =>
        new Promise<void>((resolve) => {
          socket.once("close", () => resolve());
          socket.terminate();
        })
    );
    await Promise.all(closed);
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
  assert.equal(server.clients.size, 0);
});

test("old connected reports are never presented as current healthy state", async () => {
  const { manabiStatusCode } = await import("../commands/status.js");
  const now = Date.now();
  assert.equal(
    manabiStatusCode(
      { code: "connected", observed_at: new Date(now - 30000).toISOString() },
      now
    ),
    "connected"
  );
  assert.match(
    manabiStatusCode(
      {
        code: "connected",
        observed_at: new Date(now - 7 * 86400000).toISOString(),
      },
      now
    ),
    /stale/
  );
  assert.match(
    manabiStatusCode({ code: "connected", observed_at: "invalid" }, now),
    /stale/
  );
  assert.equal(
    manabiStatusCode(
      { code: "credential_rejected", observed_at: new Date(now).toISOString() },
      now
    ),
    "credential_rejected"
  );
});
