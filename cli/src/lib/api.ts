/**
 * Thin HTTP client. Everything goes through `apiFetch` which handles
 * auth headers + JSON parsing + error surfacing.
 */

import { readConfig, writeConfig } from "./config.js";

export interface RootFolder {
  id: string;
  name: string;
  kind: "folder" | "repo";
  parent_id: string | null;
}

export interface Folder {
  id: string;
  name: string;
  kind?: "folder" | "repo";
  parent_id: string | null;
  user_id: string;
  created_at: string;
}

async function apiFetch<T>(
  path: string,
  init: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const cfg = readConfig();
  const url = `${cfg.api_base}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  const auth = init.auth ?? true;
  if (auth && cfg.access_token) {
    headers["Authorization"] = `Bearer ${cfg.access_token}`;
  }
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      // not JSON
    }
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ── Auth ────────────────────────────────────────────────────────────

export async function sendOtp(email: string): Promise<void> {
  await apiFetch("/api/cli/otp/send", {
    method: "POST",
    auth: false,
    body: JSON.stringify({ email }),
  });
}

export async function verifyOtp(
  email: string,
  token: string,
): Promise<{
  access_token: string;
  refresh_token: string;
  expires_at: number;
  user: { id: string; email: string };
}> {
  return apiFetch("/api/cli/otp/verify", {
    method: "POST",
    auth: false,
    body: JSON.stringify({ email, token }),
  });
}

export async function whoami(): Promise<{
  user_id: string;
  root_folders: RootFolder[];
}> {
  return apiFetch("/api/cli/whoami");
}

// ── Folders + integrations ─────────────────────────────────────────

export async function listRootFolders(): Promise<Folder[]> {
  return apiFetch<Folder[]>("/api/folders");
}

export async function listChildren(parentId: string): Promise<Folder[]> {
  return apiFetch<Folder[]>(`/api/folders?parent_id=${parentId}`);
}

export async function createFolder(
  name: string,
  parent_id: string | null,
): Promise<Folder> {
  return apiFetch("/api/folders", {
    method: "POST",
    body: JSON.stringify({ name, parent_id }),
  });
}

/** Turn a folder into a repo (or rename it, or both). */
export async function updateFolder(
  id: string,
  updates: { name?: string; kind?: "folder" | "repo" },
): Promise<Folder> {
  return apiFetch(`/api/folders/${id}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
}

export async function connectGitHub(args: {
  root_folder_id: string;
  repo_url: string;
  token?: string;
  since_days?: number;
}): Promise<unknown> {
  return apiFetch("/api/github/connect", {
    method: "POST",
    body: JSON.stringify({ since_days: 30, ...args }),
  });
}

export async function mintScopedApiKey(args: {
  scope_folder_id: string;
  name: string;
}): Promise<{
  key: string;
  id: string;
  scope_folder_name: string;
  mcp_config: unknown;
}> {
  return apiFetch("/api/cli/mint-api-key", {
    method: "POST",
    body: JSON.stringify(args),
  });
}
