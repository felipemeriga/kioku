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
  chmodSync,
} from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { setTimeout as sleep } from "node:timers/promises";
import { spawnSync } from "node:child_process";
import { configDir, readConfig } from "./config.js";
import { machineInfo } from "./manabi-machine.js";
import {
  recordInitializedRepo,
  inventoryPath,
  type AgentProvider,
} from "./manabi-inventory.js";
import { VERSION } from "./version.js";
import { registerManabi } from "./api.js";
import { installManabiService } from "./manabi-service.js";
import { websocketUrl, type ManabiConnection } from "./manabi-client.js";

// Bun release builds define this constant; normal Node/npm execution leaves it absent.
declare const KIOKU_STANDALONE: boolean;
export const standaloneManabi =
  typeof KIOKU_STANDALONE !== "undefined" && KIOKU_STANDALONE;

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
    join(dist, "lib/manabi-inventory.js"),
    join(dist, "lib/manabi-machine.js"),
  ];
  const digest = createHash("sha256");
  for (const file of files) digest.update(readFileSync(file));
  digest.update(readFileSync(join(ws, "package.json")));
  const target = join(root, "runtime", digest.digest("hex").slice(0, 16));
  if (!existsSync(join(target, "ready"))) {
    const temp = `${target}.${randomUUID()}.tmp`;
    mkdirSync(join(temp, "lib"), { recursive: true, mode: 0o700 });
    cpSync(files[0], join(temp, "manabi-entry.js"));
    for (const file of files.slice(1))
      cpSync(file, join(temp, "lib", file.split(/[\\/]/).at(-1)!));
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

export function stageManabiBinary(
  root: string,
  source = process.execPath
): string {
  const digest = createHash("sha256")
    .update(readFileSync(source))
    .digest("hex")
    .slice(0, 16);
  const target = join(root, "runtime", `bin-${digest}`);
  const name = process.platform === "win32" ? "kioku.exe" : "kioku";
  const executable = join(target, name);
  if (!existsSync(executable)) {
    const temp = `${target}.${randomUUID()}.tmp`;
    mkdirSync(temp, { recursive: true, mode: 0o700 });
    cpSync(source, join(temp, name));
    chmodSync(join(temp, name), 0o700);
    renameSync(temp, target);
  }
  return executable;
}

// Keep a package-manager's stable symlink instead of its disposable version path.
export function manabiNodeExecutable(
  source = process.execPath,
  searchPath = process.env.PATH ?? "",
  platform = process.platform
): string {
  const resolved = realpathSync(source);
  const name = platform === "win32" ? "node.exe" : "node";
  for (const directory of searchPath.split(delimiter)) {
    if (!isAbsolute(directory)) continue;
    const candidate = join(directory, name);
    try {
      if (realpathSync(candidate) === resolved) return candidate;
    } catch {
      /* Not this Node installation. */
    }
  }
  return resolved;
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
  try {
    return await withManabiLock(join(configDir(), "manabi"), installManabi);
  } catch (error) {
    const root = dirname(manabiConfigPath());
    try {
      mkdirSync(root, { recursive: true, mode: 0o700 });
      writeFileSync(
        join(root, "status.json"),
        JSON.stringify({
          code: "startup_failed",
          observed_at: new Date().toISOString(),
        }),
        { mode: 0o600 }
      );
    } catch {
      /* Original startup error remains actionable even if state cannot be saved. */
    }
    throw error;
  }
}

/** Refresh an existing service after a CLI replacement, without needing network access. */
export async function refreshInstalledManabi(): Promise<boolean> {
  const path = manabiConfigPath();
  if (!existsSync(path)) return false;
  await withManabiLock(dirname(path), async () => {
    const state = JSON.parse(readFileSync(path, "utf8")) as State;
    if (
      !state.id ||
      !state.api_base ||
      !state.user_id ||
      !/^[a-f0-9]{64}$/.test(state.secret)
    ) throw new Error("Existing Manabi connection is invalid");
    startManabiService(path, state);
  });
  return true;
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
    name: machineInfo().name,
    platform: `${process.platform}-${process.arch}`,
    version: VERSION,
  });
  startManabiService(path, state);
}

function startManabiService(path: string, state: State): void {
  const entry = standaloneManabi
    ? "internal-manabi-run"
    : stageManabiRuntime(dirname(path));
  const executable = standaloneManabi
    ? stageManabiBinary(dirname(path))
    : manabiNodeExecutable();
  // No shell interpolation: executable and argument paths remain separate values.
  installManabiService({
    platform: process.platform,
    home: homedir(),
    root: dirname(path),
    executable,
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

export async function registerManabiRepo(repo: {
  path: string;
  folder_id: string;
  name: string;
  agents: AgentProvider[];
}): Promise<void> {
  const cfg = readConfig();
  if (!cfg.user_id)
    throw new Error("Sign in before registering a Manabi repository");
  const identity = { api_base: cfg.api_base, user_id: cfg.user_id };
  await withManabiLock(dirname(manabiConfigPath()), async () =>
    recordInitializedRepo(inventoryPath(manabiConfigPath()), identity, repo)
  );
}
