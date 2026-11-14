import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  existsSync,
  fstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { configDir, readConfig } from "./config.js";
import type { ResolvedAccess } from "./secret-exec.js";

export interface SecretDevice {
  root_id: string;
  device_id: string;
  device_token: string;
  expires_at: string;
}
export interface BindingSelection {
  binding_id: string;
  revision: number;
}
export const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export function parseBindings(raw: string[]): BindingSelection[] {
  if (!raw.length || raw.length > 8)
    throw Error("Select between one and eight bindings.");
  const result = raw.map((value) => {
    const [id, revision, ...extra] = value.split("@");
    if (
      !UUID.test(id) ||
      !revision ||
      !/^\d{1,9}$/.test(revision) ||
      Number(revision) < 1 ||
      extra.length
    )
      throw Error("Use --binding UUID@revision.");
    return { binding_id: id, revision: Number(revision) };
  });
  if (new Set(result.map((b) => b.binding_id)).size !== result.length)
    throw Error("A binding can only be selected once.");
  return result;
}
export function secureApiBase(raw: string): URL {
  const url = new URL(raw);
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/" ||
    (url.protocol !== "https:" && !(url.protocol === "http:" && local))
  )
    throw Error(
      "Secret access requires an HTTPS API origin (HTTP allowed only on loopback).",
    );
  return url;
}
export async function secretRequest<T>(
  base: string,
  path: string,
  token: string | undefined,
  body?: unknown,
): Promise<T> {
  const origin = secureApiBase(base);
  if (!path.startsWith("/api/")) throw Error("Invalid access endpoint.");
  const controller = new AbortController(),
    timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(new URL(path, origin), {
      method: body === undefined ? "GET" : "POST",
      redirect: "error",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      await response.body?.cancel();
      throw Error(
        response.status === 401
          ? "Access authentication expired. Enroll this computer again."
          : response.status === 403
            ? "This computer is not authorized for the selected resource."
            : response.status === 409
              ? "The binding changed. Refresh the resource mapping."
              : "Secret access failed. Check the resource and vault availability.",
      );
    }
    if (!response.body) throw Error("Empty access response.");
    const reader = response.body.getReader();
    const parts: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 1048576) {
        await reader.cancel();
        throw Error("Access response exceeds supported limits.");
      }
      parts.push(value);
    }
    try {
      return JSON.parse(Buffer.concat(parts).toString("utf8")) as T;
    } catch {
      throw Error("Invalid access response.");
    }
  } catch (e) {
    if (
      e instanceof Error &&
      /^(Access |This computer|The binding|Secret access|Empty access|Invalid access)/.test(
        e.message,
      )
    )
      throw e;
    throw Error(
      "Secret access could not reach the server securely. Try again.",
    );
  } finally {
    clearTimeout(timer);
  }
}
function devicePath(root: string, base: string) {
  if (!UUID.test(root)) throw Error("Use a root folder UUID.");
  const origin = secureApiBase(base).origin;
  return join(
    configDir(),
    "secret-devices",
    createHash("sha256")
      .update(origin + "|" + root)
      .digest("hex") + ".json",
  );
}
export function saveSecretDevice(
  device: SecretDevice,
  base = readConfig().api_base,
) {
  if (
    !UUID.test(device.root_id) ||
    !UUID.test(device.device_id) ||
    !device.device_token.startsWith("ksd_") ||
    !Number.isFinite(Date.parse(device.expires_at))
  )
    throw Error("Invalid device enrollment.");
  const path = devicePath(device.root_id, base);
  mkdirSync(join(configDir(), "secret-devices"), {
    recursive: true,
    mode: 0o700,
  });
  const temp = path + "." + randomUUID() + ".tmp";
  try {
    writeFileSync(temp, JSON.stringify(device), { mode: 0o600, flag: "wx" });
    renameSync(temp, path);
  } finally {
    rmSync(temp, { force: true });
  }
}
export function readSecretDevice(
  root: string,
  base = readConfig().api_base,
): SecretDevice {
  const path = devicePath(root, base);
  if (!existsSync(path))
    throw Error(
      "Enroll this computer first: kioku access enroll --root " + root,
    );
  let fd: number | undefined;
  try {
    fd = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW || 0));
    const stat = fstatSync(fd);
    if (
      !stat.isFile() ||
      (process.platform !== "win32" && (stat.mode & 0o077) !== 0) ||
      stat.size > 16384
    )
      throw Error();
    const d = JSON.parse(readFileSync(fd, "utf8")) as SecretDevice;
    if (
      d.root_id !== root ||
      !UUID.test(d.device_id) ||
      !d.device_token?.startsWith("ksd_") ||
      !Number.isFinite(Date.parse(d.expires_at)) ||
      Date.parse(d.expires_at) <= Date.now()
    )
      throw Error();
    return d;
  } catch {
    throw Error(
      "Device credential is invalid or expired. Enroll this computer again.",
    );
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}
export function forgetSecretDevice(root: string, base = readConfig().api_base) {
  rmSync(devicePath(root, base), { force: true });
}
export async function resolveSecretAccess(
  root: string,
  bindings: BindingSelection[],
): Promise<ResolvedAccess> {
  const cfg = readConfig(),
    device = readSecretDevice(root, cfg.api_base);
  return secretRequest<ResolvedAccess>(
    cfg.api_base,
    "/api/secret-access/resolve",
    device.device_token,
    { root_id: root, invocation_id: randomUUID(), bindings },
  );
}
