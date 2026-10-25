import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { WebSocketServer } from "ws";
import {
  stageManabiRuntime,
  stageManabiBinary,
  loadOrCreateIdentity,
  withManabiLock,
  writeManabiConfig,
} from "./manabi.js";
import { installManabiService } from "./manabi-service.js";
import { reconnectDelay, runManabi, websocketUrl } from "./manabi-client.js";

test("identity is reused across repositories and separated by account/backend", () => {
  const root = mkdtempSync(join(tmpdir(), "manabi-identity-"));
  try {
    const path = join(root, "connection.json");
    const first = loadOrCreateIdentity(path, "https://kioku.example", "user-a");
    writeManabiConfig(path, first);
    assert.deepEqual(
      loadOrCreateIdentity(path, first.api_base, "user-a"),
      first
    );
    assert.notEqual(
      loadOrCreateIdentity(path, first.api_base, "user-b").id,
      first.id
    );
    assert.notEqual(
      loadOrCreateIdentity(path, "https://other.example", "user-a").id,
      first.id
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("concurrent init installations are serialized", async () => {
  const root = mkdtempSync(join(tmpdir(), "manabi-lock-"));
  let active = 0;
  let peak = 0;
  try {
    await Promise.all(
      [1, 2, 3].map(() =>
        withManabiLock(root, async () => {
          peak = Math.max(peak, ++active);
          await sleep(20);
          active--;
        })
      )
    );
    assert.equal(peak, 1);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("reconnection delay grows exponentially, jitters and caps", () => {
  assert.equal(
    reconnectDelay(0, () => 0),
    500
  );
  assert.equal(
    reconnectDelay(1, () => 1),
    2000
  );
  assert.equal(
    reconnectDelay(20, () => 1),
    60_000
  );
  assert.equal(
    reconnectDelay(1000, () => 0),
    30_000
  );
  assert.equal(
    websocketUrl("https://example.com"),
    "wss://example.com/api/remotes/connect"
  );
  assert.throws(() => websocketUrl("http://example.com"));
  assert.throws(() => websocketUrl("https://user:secret@example.com"));
});

for (const platform of ["darwin", "linux", "win32"]) {
  test(`${platform} startup is installed idempotently without launching anything in tests`, () => {
    const root = mkdtempSync(join(tmpdir(), "manabi-service-"));
    const calls: { command: string; args: string[] }[] = [];
    let started = 0;
    const options = {
      platform,
      home: root,
      root,
      uid: 501,
      executable: "/node path/node",
      entry: join(root, "runtime/entry.js"),
      config: join(root, "connection.json"),
      run: (command: string, args: string[]) => {
        calls.push({ command, args });
        return { status: 0, stdout: "", stderr: "" };
      },
      beforeStart: () => {
        started++;
      },
    };
    try {
      installManabiService(options);
      installManabiService(options);
      assert.equal(started, 2);
      if (platform === "darwin") {
        const plist = readFileSync(
          join(root, "Library/LaunchAgents/com.kioku.manabi.plist"),
          "utf8"
        );
        assert.match(plist, /KeepAlive/);
        assert.match(plist, /node path/);
        assert.equal(
          calls.filter((call) => call.args[0] === "bootstrap").length,
          1
        );
      } else if (platform === "linux") {
        const unit = readFileSync(
          join(root, ".config/systemd/user/kioku-manabi.service"),
          "utf8"
        );
        assert.match(unit, /Restart=always/);
        assert.match(unit, /StartLimitIntervalSec=0/);
        assert.match(unit, /ExecStart="\/node path\/node"/);
        assert.equal(
          calls.filter((call) => call.args.includes("restart")).length,
          1
        );
      } else {
        const script = Buffer.from(calls[0].args.at(-1)!, "base64").toString(
          "utf16le"
        );
        assert.match(script, /IgnoreNew/);
        assert.match(script, /RepetitionInterval/);
        assert.match(script, /LogonType Interactive/);
        assert.doesNotMatch(script, /secret/);
      }
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
}

test("service installation failure is surfaced instead of claiming Manabi started", () => {
  const root = mkdtempSync(join(tmpdir(), "manabi-failure-"));
  try {
    assert.throws(
      () =>
        installManabiService({
          platform: "linux",
          home: root,
          root,
          executable: "/node",
          entry: "/entry",
          config: "/config",
          run: () => ({ status: 1, stdout: "", stderr: "No user bus" }),
          beforeStart: () =>
            assert.fail("must not write config without user service manager"),
        }),
      /startup failed/
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

async function server() {
  const server = new WebSocketServer({ port: 0, host: "127.0.0.1" });
  await once(server, "listening");
  const port = (server.address() as { port: number }).port;
  return {
    server,
    config: {
      id: "machine",
      secret: "a".repeat(64),
      api_base: `http://127.0.0.1:${port}`,
    },
  };
}

test("real sockets reconnect after a dropped connection and reset only after stable health", async () => {
  const { server: wsServer, config } = await server();
  const controller = new AbortController();
  let connections = 0;
  const attempts: number[] = [];
  wsServer.on("connection", (socket) => {
    const index = ++connections;
    socket.on("message", (raw) => {
      const message = JSON.parse(raw.toString());
      if (message.type === "hello") {
        assert.equal(message.secret, config.secret);
        socket.send(JSON.stringify({ type: "ready" }));
        setTimeout(() => socket.terminate(), index < 3 ? 10 : 60);
      } else {
        socket.send(JSON.stringify({ type: "ack" }));
      }
    });
    if (index === 4) setTimeout(() => controller.abort(), 10);
  });
  const deadline = setTimeout(() => controller.abort(), 2000);
  try {
    await runManabi({
      signal: controller.signal,
      readConnection: () => config,
      heartbeatMs: 5,
      timeoutMs: 100,
      stableMs: 30,
      delay: (attempt) => {
        attempts.push(attempt);
        return 2;
      },
    });
    assert.equal(connections, 4);
    assert.deepEqual(attempts.slice(0, 3), [0, 1, 0]);
  } finally {
    clearTimeout(deadline);
    for (const client of wsServer.clients) client.terminate();
    wsServer.close();
  }
});

test("half-open connections time out and reconnect without an application ack", async () => {
  const { server: wsServer, config } = await server();
  const controller = new AbortController();
  let connections = 0;
  wsServer.on("connection", (socket) => {
    connections++;
    socket.once("message", () => socket.send('{"type":"ready"}'));
    if (connections === 2) controller.abort();
  });
  const deadline = setTimeout(() => controller.abort(), 1000);
  try {
    await runManabi({
      signal: controller.signal,
      readConnection: () => config,
      heartbeatMs: 5,
      timeoutMs: 25,
      delay: () => 1,
    });
    assert.equal(connections, 2);
  } finally {
    clearTimeout(deadline);
    for (const client of wsServer.clients) client.terminate();
    wsServer.close();
  }
});

test("credential rejection retries indefinitely and abort interrupts backoff", async () => {
  const { server: wsServer, config } = await server();
  const controller = new AbortController();
  let attempts = 0;
  wsServer.on("connection", (socket) => socket.close(4401));
  const deadline = setTimeout(() => controller.abort(), 1000);
  try {
    await runManabi({
      signal: controller.signal,
      readConnection: () => config,
      delay: () => {
        if (++attempts === 4) controller.abort();
        return 1;
      },
    });
    assert.equal(attempts, 4);
  } finally {
    clearTimeout(deadline);
    wsServer.close();
  }
});

test("staged daemon runs independently from CLI package and exits on signal", async () => {
  const { server: wsServer, config } = await server();
  const root = mkdtempSync(join(tmpdir(), "manabi-runtime-"));
  const configPath = join(root, "connection.json");
  writeManabiConfig(configPath, { ...config, user_id: "alice" });
  const entry = stageManabiRuntime(root);
  const child = spawn(process.execPath, [entry, configPath], {
    cwd: root,
    stdio: "ignore",
  });
  const deadline = setTimeout(() => child.kill("SIGKILL"), 3000);
  try {
    const [socket] = await once(wsServer, "connection");
    const [raw] = await once(socket, "message");
    assert.equal(JSON.parse(raw.toString()).secret, config.secret);
    const exited = once(child, "exit");
    child.kill("SIGTERM");
    const [code] = await exited;
    assert.equal(code, 0);
  } finally {
    clearTimeout(deadline);
    child.kill("SIGKILL");
    for (const client of wsServer.clients) client.terminate();
    wsServer.close();
    rmSync(root, { recursive: true, force: true });
  }
});

test("standalone runtime snapshot is reused and changes when executable content changes", () => {
  const root = mkdtempSync(join(tmpdir(), "manabi-binary-"));
  const source = join(root, "source");
  try {
    writeFileSync(source, "binary-one");
    const first = stageManabiBinary(root, source);
    assert.equal(stageManabiBinary(root, source), first);
    assert.equal(readFileSync(first, "utf8"), "binary-one");
    writeFileSync(source, "binary-two");
    const next = stageManabiBinary(root, source);
    assert.notEqual(first, next);
    assert.equal(readFileSync(next, "utf8"), "binary-two");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("macOS runtime upgrades tolerate transient launchd unload/bootstrap races", () => {
  const root = mkdtempSync(join(tmpdir(), "manabi-launchd-race-"));
  let attempts = 0;
  try {
    installManabiService({
      platform: "darwin",
      home: root,
      root,
      uid: 501,
      executable: "/binary",
      entry: "internal-manabi-run",
      config: "/config",
      run: (_command, args) => ({
        status: args[0] === "bootstrap" && ++attempts === 1 ? 5 : 0,
        stdout: "",
        stderr: "",
      }),
      beforeStart: () => {},
    });
    assert.equal(attempts, 2);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("inventory snapshots deduplicate until changed and resend after reconnect", async () => {
  const { server: wsServer, config } = await server();
  const controller = new AbortController();
  let revision = 1;
  let received = 0;
  let connections = 0;
  let connectedStatuses = 0;
  let firstAcknowledged: () => void = () => {};
  const firstAck = new Promise<void>((resolve) => {
    firstAcknowledged = resolve;
  });
  controller.signal.addEventListener("abort", () => firstAcknowledged(), {
    once: true,
  });
  wsServer.on("connection", (socket) => {
    connections++;
    socket.on("message", (raw) => {
      const message = JSON.parse(raw.toString());
      if (message.type === "hello") socket.send('{"type":"ready"}');
      if (message.type === "heartbeat") socket.send('{"type":"ack"}');
      if (message.type === "inventory") {
        received++;
        assert.equal(message.revision.length, 64);
        assert.equal(
          JSON.stringify(message.data).includes(config.secret),
          false
        );
        socket.send(
          JSON.stringify({ type: "inventory_ack", revision: message.revision })
        );
        if (received === 2) socket.terminate();
        else if (received === 3) controller.abort();
      }
    });
  });
  const deadline = setTimeout(() => controller.abort(), 3000);
  let running: Promise<void> | undefined;
  try {
    running = runManabi({
      signal: controller.signal,
      readConnection: () => config,
      snapshot: () => ({ revision }),
      status: (code) => {
        if (code === "connected" && ++connectedStatuses === 2)
          firstAcknowledged();
      },
      heartbeatMs: 50,
      timeoutMs: 500,
      delay: () => 1,
    });
    await firstAck;
    await sleep(160);
    assert.equal(received, 1);
    revision = 2;
    await running;
    assert.equal(received, 3);
    assert.equal(connections, 2);
  } finally {
    controller.abort();
    await running;
    clearTimeout(deadline);
    for (const socket of wsServer.clients) socket.terminate();
    wsServer.close();
  }
});
