import { hostname } from "node:os";
import { setTimeout as sleep } from "node:timers/promises";
import { readConfig } from "../lib/config.js";
import { whoami } from "../lib/api.js";
import { tryOpenBrowser } from "../lib/browser.js";
import {
  UUID,
  forgetSecretDevice,
  parseBindings,
  resolveSecretAccess,
  saveSecretDevice,
  secureApiBase,
  secretRequest,
  type SecretDevice,
} from "../lib/secret-access.js";
import { runSecretCommand } from "../lib/secret-exec.js";

function rootId(root: string) {
  if (!UUID.test(root)) throw Error("Use --root with the root folder UUID.");
  return root;
}
async function userToken() {
  secureApiBase(readConfig().api_base);
  await whoami();
  const cfg = readConfig();
  if (!cfg.access_token) throw Error("Run kioku login first.");
  return cfg;
}
export async function enrollAccess(opts: {
  root: string;
  label?: string;
  browser?: boolean;
  fileCredentialStore?: boolean;
}) {
  const root = rootId(opts.root);
  if (!opts.fileCredentialStore)
    throw Error(
      "This build uses a separate mode-0600 device credential file. Add --file-credential-store to acknowledge local file storage.",
    );
  const cfg = await userToken();
  const label = opts.label || hostname();
  if (!label.trim() || label.length > 120)
    throw Error("Computer label must contain 1–120 characters.");
  const start = await secretRequest<{
    request_id: string;
    device_code: string;
    verification_url: string;
    expires_at: string;
  }>(cfg.api_base, "/api/secret-access/enroll", cfg.access_token, {
    root_id: root,
    label,
  });
  const url = new URL(start.verification_url);
  if (
    url.protocol !== "https:" &&
    !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
  )
    throw Error("Enrollment returned an insecure approval URL.");
  if (!UUID.test(start.request_id) || typeof start.device_code !== "string")
    throw Error("Invalid enrollment response.");
  console.log(
    "Approve this computer and select resource permissions in your browser:",
  );
  console.log(url.toString());
  if (opts.browser !== false) tryOpenBrowser(url.toString());
  const deadline = Math.min(Date.parse(start.expires_at), Date.now() + 600000);
  if (!Number.isFinite(deadline) || deadline <= Date.now())
    throw Error("Enrollment expired. Start again.");
  while (Date.now() < deadline) {
    const result = await secretRequest<
      { status: string } & Partial<SecretDevice>
    >(cfg.api_base, "/api/secret-access/enroll/poll", undefined, {
      request_id: start.request_id,
      device_code: start.device_code,
    });
    if (result.status === "approved") {
      if (result.root_id !== root)
        throw Error("Enrollment returned a different root.");
      saveSecretDevice(result as SecretDevice, cfg.api_base);
      console.log(
        "Computer enrolled. Device credential saved separately with mode 0600; no vault values were stored.",
      );
      return;
    }
    if (["denied", "expired"].includes(result.status))
      throw Error("Enrollment was denied or expired.");
    if (result.status !== "pending") throw Error("Invalid enrollment status.");
    await sleep(2500);
  }
  throw Error("Enrollment timed out. Start again.");
}
export async function listAccess(opts: { root: string }) {
  const root = rootId(opts.root),
    cfg = await userToken();
  const data = await secretRequest<{
    resources: Array<{ id: string; name: string }>;
    environments: Array<{ id: string; name: string; slug: string }>;
    bindings: Array<{
      id: string;
      resource_id: string;
      environment_id: string | null;
      revision: number;
      enabled: boolean;
    }>;
  }>(cfg.api_base, `/api/root-access/${root}`, cfg.access_token);
  const names = new Map(data.resources.map((r) => [r.id, r.name]));
  const envs = new Map(data.environments.map((e) => [e.id, e.name || e.slug]));
  for (const binding of data.bindings) {
    console.log(
      `${names.get(binding.resource_id) || "Resource"} | ${binding.environment_id ? envs.get(binding.environment_id) || "Environment" : "Shared"} | ${binding.id}@${binding.revision}${binding.enabled ? "" : " | disabled"}`,
    );
  }
  if (!data.bindings.length)
    console.log("No resource bindings configured for this root.");
}
export function forgetAccess(opts: { root: string }) {
  forgetSecretDevice(rootId(opts.root));
  console.log(
    "Local device credential removed. Revoke the computer in Kioku to block other copies.",
  );
}
export async function execAccess(
  command: string[],
  opts: { root: string; binding: string[] },
) {
  const root = rootId(opts.root),
    bindings = parseBindings(opts.binding);
  if (!command.length) throw Error("Provide a command after --.");
  const resolved = await resolveSecretAccess(root, bindings);
  process.exitCode = await runSecretCommand(command, resolved);
}
