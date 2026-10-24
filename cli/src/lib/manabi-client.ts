import WebSocket from "ws";
import { setTimeout as sleep } from "node:timers/promises";

export interface ManabiConnection {
  id: string;
  secret: string;
  api_base: string;
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
  readConnection: () => ManabiConnection | null;
  log?: (message: string) => void;
  heartbeatMs?: number;
  timeoutMs?: number;
  stableMs?: number;
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
    } catch {
      log("Manabi connection unavailable; retrying.");
    }
    if (signal.aborted) break;
    if (stable) attempt = 0;
    const delay = (options.delay ?? reconnectDelay)(attempt++);
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
    let readyAt = 0;
    let lastAck = Date.now();
    let authenticated = false;
    let acknowledgedHeartbeat = false;
    const stop = () => socket.terminate();
    options.signal.addEventListener("abort", stop, { once: true });
    const check = setInterval(() => {
      let current: ManabiConnection | null;
      try {
        current = options.readConnection();
      } catch {
        stop();
        return;
      }
      if (
        JSON.stringify(current) !== JSON.stringify(config) ||
        Date.now() - lastAck > timeoutMs
      ) {
        stop();
        return;
      }
      if (authenticated && socket.readyState === WebSocket.OPEN)
        socket.send(JSON.stringify({ type: "heartbeat" }));
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
        const message = JSON.parse(raw.toString()) as { type?: string };
        if (message.type === "ready" && !authenticated) {
          authenticated = true;
          readyAt = Date.now();
          options.log?.("Manabi connected.");
        } else if (message.type !== "ack" || !authenticated) {
          stop();
          return;
        }
        if (message.type === "ack") acknowledgedHeartbeat = true;
        lastAck = Date.now();
      } catch {
        stop();
      }
    });
    socket.on("error", () => stop());
    socket.once("close", (code) => {
      clearInterval(check);
      options.signal.removeEventListener("abort", stop);
      if (code === 4401)
        options.log?.(
          "Manabi credential rejected. Re-run kioku init to register again."
        );
      resolve(
        authenticated &&
          acknowledgedHeartbeat &&
          Date.now() - lastAck <= timeoutMs &&
          Date.now() - readyAt >= (options.stableMs ?? 60_000)
      );
    });
  });
}
