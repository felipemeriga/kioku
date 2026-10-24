import { createHash, randomBytes, randomUUID } from "node:crypto";
import {
  cpSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
  rmSync,
  realpathSync,
  statSync,
} from "node:fs";
import { hostname, homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { setTimeout as sleep } from "node:timers/promises";
import { spawnSync } from "node:child_process";
import { configDir, readConfig } from "./config.js";
import { VERSION } from "./version.js";
import { registerManabi } from "./api.js";
import { installManabiService } from "./manabi-service.js";
import { websocketUrl, type ManabiConnection } from "./manabi-client.js";

interface State extends ManabiConnection {
  user_id: string;
}
export function manabiConfigPath(): string {
  return join(configDir(), "manabi", "connection.json");
}

export function loadOrCreateIdentity(
  path: string,
  apiBase: string,
  userId: string
): State {
  try {
    const prior = JSON.parse(readFileSync(path, "utf8")) as State;
    if (
      prior.api_base === apiBase &&
      prior.user_id === userId &&
      /^[a-f0-9]{64}$/.test(prior.secret)
    )
      return prior;
  } catch {
    /* First init or a different account/backend. */
  }
  let id: string = randomUUID();
  try {
    const identity = JSON.parse(
      readFileSync(`${path}.identity`, "utf8")
    ) as State;
    if (identity.api_base === apiBase && identity.user_id === userId)
      id = identity.id;
  } catch {
    /* No previously registered identity. */
  }
  return {
    id,
    secret: randomBytes(32).toString("hex"),
    api_base: apiBase,
    user_id: userId,
  };
}

export function writeManabiConfig(path: string, state: State): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temp = `${path}.${randomUUID()}.tmp`;
  writeFileSync(temp, JSON.stringify(state), { mode: 0o600 });
  renameSync(temp, path);
  saveIdentity(path, state);
}

function saveIdentity(path: string, state: State): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temp = `${path}.identity.${randomUUID()}.tmp`;
  writeFileSync(
    temp,
    JSON.stringify({
      id: state.id,
      api_base: state.api_base,
      user_id: state.user_id,
    }),
    { mode: 0o600 }
  );
  renameSync(temp, `${path}.identity`);
}

export function clearManabiConnection(): void {
  rmSync(manabiConfigPath(), { force: true });
}

export function stageManabiRuntime(root: string): string {
  const dist = fileURLToPath(new URL("../", import.meta.url));
  const ws = dirname(createRequire(import.meta.url).resolve("ws/package.json"));
  const files = [
    join(dist, "manabi-entry.js"),
    join(dist, "lib/manabi-client.js"),
  ];
  const digest = createHash("sha256");
  for (const file of files) digest.update(readFileSync(file));
  digest.update(readFileSync(join(ws, "package.json")));
  const target = join(root, "runtime", digest.digest("hex").slice(0, 16));
  if (!existsSync(join(target, "ready"))) {
    const temp = `${target}.${randomUUID()}.tmp`;
    mkdirSync(join(temp, "lib"), { recursive: true, mode: 0o700 });
    cpSync(files[0], join(temp, "manabi-entry.js"));
    cpSync(files[1], join(temp, "lib/manabi-client.js"));
    cpSync(ws, join(temp, "node_modules/ws"), { recursive: true });
    writeFileSync(join(temp, "package.json"), '{"type":"module"}');
    writeFileSync(join(temp, "ready"), "");
    try {
      renameSync(temp, target);
    } catch (error) {
      rmSync(temp, { recursive: true, force: true });
      if (!existsSync(join(target, "ready"))) throw error;
    }
  }
  return join(target, "manabi-entry.js");
}

export async function withManabiLock<T>(
  root: string,
  action: () => Promise<T>
): Promise<T> {
  mkdirSync(root, { recursive: true, mode: 0o700 });
  const lock = join(root, "install.lock");
  const deadline = Date.now() + 90_000;
  while (true) {
    try {
      mkdirSync(lock);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      try {
        if (Date.now() - statSync(lock).mtimeMs > 120_000) {
          rmSync(lock, { recursive: true, force: true });
          continue;
        }
      } catch {
        continue;
      }
      if (Date.now() > deadline)
        throw new Error(
          "Another kioku init is installing Manabi. Retry shortly."
        );
      await sleep(100);
    }
  }
  try {
    return await action();
  } finally {
    rmSync(lock, { recursive: true, force: true });
  }
}

export async function ensureManabi(): Promise<void> {
  return withManabiLock(join(configDir(), "manabi"), installManabi);
}

async function installManabi(): Promise<void> {
  const cfg = readConfig();
  if (!cfg.user_id) throw new Error("Sign in before installing Manabi");
  websocketUrl(cfg.api_base);
  const path = manabiConfigPath();
  const state = loadOrCreateIdentity(path, cfg.api_base, cfg.user_id);
  saveIdentity(path, state);
  await registerManabi({
    id: state.id,
    secret: state.secret,
    name: hostname(),
    platform: `${process.platform}-${process.arch}`,
    version: VERSION,
  });
  const entry = stageManabiRuntime(dirname(path));
  // No shell interpolation: executable and argument paths remain separate values.
  installManabiService({
    platform: process.platform,
    home: homedir(),
    root: dirname(path),
    executable: realpathSync(process.execPath),
    entry,
    config: path,
    uid: process.getuid?.(),
    run: (command, args) => {
      const result = spawnSync(command, args, {
        encoding: "utf8",
        timeout: 20_000,
      });
      return {
        status: result.status,
        stdout: result.stdout ?? "",
        stderr: result.stderr ?? "",
      };
    },
    beforeStart: () => writeManabiConfig(path, state),
  });
}
