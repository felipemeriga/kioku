import WebSocket from "ws";
import { readInventory, inventoryPath } from "./manabi-inventory.js";
import { machineInfo } from "./manabi-machine.js";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { writeFileSync, renameSync } from "node:fs";
import { readFileSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

export interface ManabiConnection {
  id: string;
  secret: string;
  api_base: string;
  user_id?: string;
}

export function websocketUrl(base: string): string {
  const url = new URL(base);
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("Manabi requires a plain backend URL");
  }
  if (url.protocol === "https:") url.protocol = "wss:";
  else if (
    url.protocol === "http:" &&
    ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  )
    url.protocol = "ws:";
  else
    throw new Error("Manabi requires HTTPS (HTTP allowed only on localhost)");
  url.pathname = `${url.pathname.replace(/\/$/, "")}/api/remotes/connect`;
  return url.toString();
}

export function reconnectDelay(attempt: number, random = Math.random): number {
  const cap = Math.min(60_000, 1000 * 2 ** Math.min(attempt, 6));
  return Math.round(cap * (0.5 + random() * 0.5));
}

interface Options {
  signal: AbortSignal;
  snapshot?: () => unknown;
  status?: (code: string) => void;
  readConnection: () => ManabiConnection | null;
  log?: (message: string) => void;
  heartbeatMs?: number;
  timeoutMs?: number;
  stableMs?: number;
  monotonicNow?: () => number;
  wallNow?: () => number;
  delay?: (attempt: number) => number;
}

export async function runManabi(options: Options): Promise<void> {
  const { signal, readConnection } = options;
  const log = options.log ?? (() => {});
  let attempt = 0;
  while (!signal.aborted) {
    let stable = false;
    try {
      const config = readConnection();
      if (config) stable = await connectOnce(config, options);
      else options.status?.("signed_out");
    } catch {
      options.status?.("connection_unavailable");
      log("Manabi connection unavailable; retrying.");
    }
    if (signal.aborted) break;
    if (stable) attempt = 0;
    const delay = (options.delay ?? reconnectDelay)(attempt);
    attempt = Math.min(attempt + 1, 6);
    log(`Manabi reconnecting in ${Math.round(delay / 1000)}s.`);
    try {
      await sleep(delay, undefined, { signal });
    } catch {
      break;
    }
  }
}

function connectOnce(
  config: ManabiConnection,
  options: Options
): Promise<boolean> {
  return new Promise((resolve) => {
    const heartbeatMs = options.heartbeatMs ?? 30_000;
    const timeoutMs = options.timeoutMs ?? 70_000;
    const socket = new WebSocket(websocketUrl(config.api_base), {
      handshakeTimeout: 10_000,
      maxPayload: 1024,
      perMessageDeflate: false,
    });
    let acknowledgedSnapshot = "";
    const sendSnapshot = () => {
      if (!options.snapshot || socket.readyState !== WebSocket.OPEN) return;
      try {
        const data = options.snapshot();
        const encoded = JSON.stringify(data);
        if (Buffer.byteLength(encoded) > 250_000) {
          options.status?.("inventory_too_large");
          return;
        }
        const revision = createHash("sha256").update(encoded).digest("hex");
        if (revision !== acknowledgedSnapshot)
          socket.send(JSON.stringify({ type: "inventory", revision, data }));
      } catch {
        options.status?.("inventory_unavailable");
      }
    };
    const now = options.monotonicNow ?? (() => performance.now());
    const wall = options.wallNow ?? Date.now;
    let readyAt = 0;
    let lastAck = now();
    let lastCheck = now();
    let lastWall = wall();
    let authenticated = false;
    let acknowledgedHeartbeat = false;
    const stop = () => socket.terminate();
    options.signal.addEventListener("abort", stop, { once: true });
    const check = setInterval(() => {
      const checkedAt = now();
      const wallAt = wall();
      // Resume from suspension or a clock jump must not preserve a stale socket.
      const interrupted =
        checkedAt - lastCheck > timeoutMs ||
        Math.abs(wallAt - lastWall - (checkedAt - lastCheck)) > timeoutMs;
      lastCheck = checkedAt;
      lastWall = wallAt;
      let current: ManabiConnection | null;
      try {
        current = options.readConnection();
      } catch {
        stop();
        return;
      }
      if (
        JSON.stringify(current) !== JSON.stringify(config) ||
        interrupted ||
        checkedAt - lastAck > timeoutMs
      ) {
        stop();
        return;
      }
      if (authenticated && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "heartbeat" }));
        sendSnapshot();
      }
    }, heartbeatMs);
    socket.on("open", () => {
      if (options.signal.aborted) {
        stop();
        return;
      }
      socket.send(
        JSON.stringify({ type: "hello", id: config.id, secret: config.secret })
      );
    });
    socket.on("message", (raw) => {
      try {
        const message = JSON.parse(raw.toString()) as {
          type?: string;
          revision?: string;
        };
        if (message.type === "inventory_ack" && authenticated) {
          acknowledgedSnapshot = message.revision ?? "";
          options.status?.("connected");
          return;
        }
        if (message.type === "inventory_error" && authenticated) {
          options.status?.("inventory_rejected");
          return;
        }
        if (message.type === "ready" && !authenticated) {
          authenticated = true;
          readyAt = now();
          options.log?.("Manabi connected.");
          options.status?.("connected");
          sendSnapshot();
        } else if (message.type !== "ack" || !authenticated) {
          stop();
          return;
        }
        if (message.type === "ack") {
          acknowledgedHeartbeat = true;
          options.status?.("connected");
        }
        lastAck = now();
      } catch {
        stop();
      }
    });
    socket.on("error", () => stop());
    socket.once("close", (code) => {
      clearInterval(check);
      options.signal.removeEventListener("abort", stop);
      options.status?.(
        code === 4401 ? "credential_rejected" : "connection_unavailable"
      );
      if (code === 4401)
        options.log?.(
          "Manabi credential rejected. Re-run kioku init to register again."
        );
      resolve(
        authenticated &&
          acknowledgedHeartbeat &&
          now() - lastAck <= timeoutMs &&
          now() - readyAt >= (options.stableMs ?? 60_000)
      );
    });
  });
}

export async function runManabiDaemon(configPath: string): Promise<void> {
  if (!configPath) throw new Error("Missing Manabi configuration path");
  const diagnostics = new ManabiDiagnostics(configPath);
  let inventoryWarnings: { code: string; observed_at: string }[] = [];
  const controller = new AbortController();
  const stop = () => controller.abort();
  process.once("SIGTERM", stop);
  process.once("SIGINT", stop);
  try {
    await runManabi({
      signal: controller.signal,
      snapshot: () => {
        const config = JSON.parse(
          readFileSync(configPath, "utf8")
        ) as ManabiConnection;
        const inventory = readInventory(inventoryPath(configPath), config);
        inventoryWarnings = inventory.warnings;
        return { ...machineInfo(), ...inventory };
      },
      status: (code) => {
        diagnostics.record(code);
        try {
          const path = join(dirname(configPath), "status.json");
          const temp = `${path}.${process.pid}.tmp`;
          writeFileSync(
            temp,
            JSON.stringify({
              code,
              observed_at: new Date().toISOString(),
              warnings: inventoryWarnings,
            }),
            { mode: 0o600 }
          );
          renameSync(temp, path);
        } catch {
          /* Presence still expires server-side if local storage is unavailable. */
        }
      },
      readConnection: () => {
        try {
          return JSON.parse(
            readFileSync(configPath, "utf8")
          ) as ManabiConnection;
        } catch {
          return null;
        }
      },
      // Connection history is bounded and contains codes only, never credentials.
      log: () => {},
    });
  } finally {
    process.removeListener("SIGTERM", stop);
    process.removeListener("SIGINT", stop);
  }
}

export class ManabiDiagnostics {
  private events: { code: string; observed_at: string }[] = [];
  private previous = "";
  private path: string;
  constructor(configPath: string) {
    this.path = join(dirname(configPath), "diagnostics.json");
    try {
      const saved: unknown = JSON.parse(readFileSync(this.path, "utf8"));
      if (Array.isArray(saved))
        this.events = saved
          .filter(
            (event) =>
              event &&
              typeof event.code === "string" &&
              /^[a-z_]{1,64}$/.test(event.code) &&
              typeof event.observed_at === "string" &&
              Number.isFinite(Date.parse(event.observed_at))
          )
          .slice(-50)
          .map(({ code, observed_at }) => ({ code, observed_at }));
    } catch {
      /* New or damaged diagnostic file: current connection still runs. */
    }
  }
  record(code: string): void {
    if (code === this.previous || !/^[a-z_]{1,64}$/.test(code)) return;
    this.previous = code;
    this.events.push({ code, observed_at: new Date().toISOString() });
    this.events = this.events.slice(-50);
    try {
      const temp = `${this.path}.${process.pid}.tmp`;
      writeFileSync(temp, JSON.stringify(this.events), { mode: 0o600 });
      renameSync(temp, this.path);
    } catch {
      /* Diagnostic storage must never stop reconnecting. */
    }
  }
}
