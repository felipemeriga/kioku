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
export const accessKey = (root: string) => ["root-access", root] as const;
const path = (root: string, suffix = "") =>
  `/api/root-access/${encodeURIComponent(root)}${suffix}`;
export async function fetchAccess(root: string): Promise<AccessCatalog> {
  return (await apiFetch(path(root))).json();
}
export async function mutateAccess<T = unknown>(
  root: string,
  suffix: string,
  method: string,
  body?: unknown,
): Promise<T> {
  const res = await apiFetch(path(root, suffix), {
    method,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  return res.status === 204 ? (undefined as T) : res.json();
}
export function accessError(error: unknown): string {
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
export function allowedVariable(name: string) {
  return (
    /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name) &&
    !/^(LD_|DYLD_|NODE_OPTIONS$|BASH_ENV$|ENV$|SHELLOPTS$|PYTHONPATH$|PYTHONSTARTUP$)/.test(
      name,
    )
  );
}
export function mappingError(text: string): string {
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
  return "";
}
export const guideBytes = (value: string) =>
  new TextEncoder().encode(value).length;
