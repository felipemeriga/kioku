import { ApiError, apiFetch } from "./api";

export interface AccessEnvironment {
  id: string;
  name: string;
  slug: string;
  sensitivity: "normal" | "production";
}
export interface AccessResource {
  id: string;
  name: string;
  description: string;
  type: "database" | "observability" | "cloud" | "other";
  aliases: string[];
  shared: boolean;
  account: string;
  region: string;
}
export interface AccessBinding {
  id: string;
  resource_id: string;
  environment_id: string | null;
  consumer: string;
  field_mapping: Record<string, string>;
  clear_env: string[];
  revision: number;
  enabled: boolean;
  has_secret: boolean;
  credential_expires_at: string | null;
  pending_operation_id: string | null;
}
export interface AccessDevice {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
  revoked_at: string | null;
}
export interface AccessGrant {
  id: string;
  device_id: string;
  binding_id: string;
  expires_at: string | null;
  revoked_at: string | null;
}
export interface AccessEvent {
  id: string;
  device_id: string;
  resource_id: string;
  binding_id: string;
  action: string;
  outcome: string;
  created_at: string;
}
export interface AccessCatalog {
  root_id: string;
  guide: { markdown: string; revision: number };
  environments: AccessEnvironment[];
  resources: AccessResource[];
  bindings: AccessBinding[];
  devices: AccessDevice[];
  grants: AccessGrant[];
  activity: AccessEvent[];
  provider: { configured: boolean };
}
export interface AccessEnrollment {
  label: string;
  expires_at: string;
  status: string;
}
export const accessKey = (root: string, owner: string) =>
  ["root-access", owner, root] as const;
const path = (root: string, suffix = "") =>
  `/api/root-access/${encodeURIComponent(root)}${suffix}`;
export class AccessTimeoutError extends Error {
  constructor(write: boolean) {
    super(
      write
        ? "The request timed out. Its outcome may be pending; refresh the resource before retrying."
        : "Loading took too long. Check your connection and try again.",
    );
    this.name = "AccessTimeoutError";
  }
}
async function accessRequest<T>(
  root: string,
  suffix: string,
  method: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const cancelled = () =>
    new DOMException("Access request cancelled.", "AbortError");
  if (signal?.aborted) throw cancelled();
  let rejectStopped: (error: Error) => void = () => {};
  const stopped = new Promise<never>((_resolve, reject) => {
    rejectStopped = reject;
  });
  const onCancel = () => {
    rejectStopped(cancelled());
    controller.abort();
  };
  signal?.addEventListener("abort", onCancel, { once: true });
  const timer = setTimeout(() => {
    rejectStopped(new AccessTimeoutError(method !== "GET"));
    controller.abort();
  }, 15000);
  const operation = (async () => {
    const response = await apiFetch(path(root, suffix), {
      method,
      cache: "no-store",
      signal: controller.signal,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (controller.signal.aborted) throw cancelled();
    return response.status === 204
      ? (undefined as T)
      : ((await response.json()) as T);
  })();
  try {
    return await Promise.race([operation, stopped]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCancel);
  }
}
export function fetchAccess(
  root: string,
  signal?: AbortSignal,
): Promise<AccessCatalog> {
  return accessRequest(root, "", "GET", undefined, signal);
}
export function mutateAccess<T = unknown>(
  root: string,
  suffix: string,
  method: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return accessRequest(root, suffix, method, body, signal);
}
export function accessError(error: unknown): string {
  if (error instanceof AccessTimeoutError) return error.message;
  if (error instanceof DOMException && error.name === "AbortError")
    return "Request cancelled.";
  if (error instanceof ApiError) {
    if (error.status === 401) return "Your session expired. Sign in again.";
    if (error.status === 403 || error.status === 404)
      return "This root or resource is unavailable to your account.";
    if (error.status === 409)
      return "This configuration changed. Refresh before saving again.";
    if (error.status === 503)
      return "The vault is unavailable. Try again shortly.";
    if (error.status === 422 || error.status === 400)
      return "Check the fields and try again. The configuration was not saved.";
  }
  return "Could not complete this request. Try again.";
}
export function resourceError(name: string, aliases: string[]): string {
  if (!name.trim() || name.trim().length > 120)
    return "Enter a resource name of 1–120 characters.";
  if (aliases.length > 20 || aliases.some((a) => a.length > 120))
    return "Use up to 20 aliases, each at most 120 characters.";
  return "";
}
export function parseMapping(text: string): Record<string, string> {
  return Object.fromEntries(
    text
      .split(/\n/)
      .filter((l) => l.trim())
      .map((l) => l.split("=").map((p) => p.trim())),
  );
}
const coreVariables = new Set([
  "PATH",
  "HOME",
  "USERPROFILE",
  "COMSPEC",
  "SYSTEMROOT",
  "PATHEXT",
]);
const runtimeVariables = new Set([
  "NODE_OPTIONS",
  "BASH_ENV",
  "ENV",
  "PYTHONSTARTUP",
  "PYTHONPATH",
  "IFS",
  "CDPATH",
  "ZDOTDIR",
  "SHELLOPTS",
  "BASHOPTS",
  "AWS_PROFILE",
  "AWS_DEFAULT_PROFILE",
  "AWS_CONFIG_FILE",
  "AWS_SHARED_CREDENTIALS_FILE",
  "AWS_WEB_IDENTITY_TOKEN_FILE",
  "AWS_ROLE_ARN",
  "AWS_ROLE_SESSION_NAME",
  "AWS_EC2_METADATA_DISABLED",
  "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
  "AWS_CONTAINER_CREDENTIALS_FULL_URI",
  "AWS_CONTAINER_AUTHORIZATION_TOKEN",
  "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
]);
export function allowedVariable(name: string) {
  const normalized = name.toUpperCase();
  return (
    /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name) &&
    !/^(LD_|DYLD_)/.test(normalized) &&
    !coreVariables.has(normalized) &&
    !runtimeVariables.has(normalized)
  );
}
export function allowedClearVariable(name: string) {
  return (
    /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name) &&
    !coreVariables.has(name.toUpperCase())
  );
}
export function mappingError(
  text: string,
  type?: AccessResource["type"],
): string {
  const lines = text.split(/\n/).filter((l) => l.trim());
  if (!lines.length || lines.length > 32) return "Add 1–32 variable mappings.";
  const seen = new Set<string>();
  for (const line of lines) {
    const parts = line.split("=").map((p) => p.trim());
    if (
      parts.length !== 2 ||
      !allowedVariable(parts[0]) ||
      !/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(parts[1])
    )
      return "Use an allowed variable and secret field: MONGO_URI=connection.";
    if (seen.has(parts[0])) return "Map each variable only once.";
    seen.add(parts[0]);
  }
  if (
    type === "cloud" &&
    (!seen.has("AWS_ACCESS_KEY_ID") || !seen.has("AWS_SECRET_ACCESS_KEY"))
  )
    return "AWS mappings require both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.";
  return "";
}
export const guideBytes = (value: string) =>
  new TextEncoder().encode(value).length;
