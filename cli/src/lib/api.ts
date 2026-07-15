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

/**
 * Rich error class so command handlers can distinguish transport errors
 * (backend down) from auth errors (session expired) from real 400/500s
 * and format a helpful message per case.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly kind: "unreachable" | "unauthorized" | "http";
  readonly hint: string | undefined;

  constructor(msg: string, opts: { status?: number; kind?: ApiError["kind"]; hint?: string } = {}) {
    super(msg);
    this.name = "ApiError";
    this.status = opts.status ?? 0;
    this.kind = opts.kind ?? "http";
    this.hint = opts.hint;
  }
}

async function apiFetch<T>(
  path: string,
  init: RequestInit & { auth?: boolean; _retry?: boolean } = {},
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
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const isRefused =
      msg.includes("ECONNREFUSED") ||
      msg.includes("connect ECONN") ||
      msg.includes("fetch failed") ||
      msg.includes("getaddrinfo");
    throw new ApiError(`Couldn't reach ${cfg.api_base}: ${msg}`, {
      kind: "unreachable",
      hint: isRefused
        ? `Is the backend running at ${cfg.api_base}? Start it, or export KIOKU_API_BASE=https://your-prod-url.`
        : `Check your network + KIOKU_API_BASE (currently ${cfg.api_base}).`,
    });
  }
  if (!res.ok) {
    // Auto-refresh on 401 — silent, one-shot. If refresh succeeds we
    // replay the original call. If not, surface the actionable hint.
    if (
      (res.status === 401 || res.status === 403) &&
      !init._retry &&
      auth &&
      cfg.refresh_token
    ) {
      const refreshed = await tryRefreshToken();
      if (refreshed) {
        return apiFetch<T>(path, { ...init, _retry: true });
      }
    }
    const text = await res.text();
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      // not JSON
    }
    if (res.status === 401 || res.status === 403) {
      throw new ApiError(`Session expired (${res.status}): ${detail}`, {
        status: res.status,
        kind: "unauthorized",
        hint: "Run: kioku login",
      });
    }
    throw new ApiError(`${res.status} ${res.statusText}: ${detail}`, {
      status: res.status,
      kind: "http",
    });
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}


/**
 * Exchange refresh_token for a new access_token via Supabase's /auth/v1/token.
 * On success, persists the new tokens to config and returns true. On
 * failure (revoked, expired, network), returns false so the caller can
 * surface a friendly re-login prompt.
 */
let _refreshInFlight: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  // Coalesce concurrent refreshes so 3 parallel API calls with an
  // expired token only trigger ONE refresh round-trip.
  if (_refreshInFlight) return _refreshInFlight;
  _refreshInFlight = (async () => {
    try {
      const cfg = readConfig();
      if (!cfg.refresh_token) return false;

      // Discover Supabase URL + anon key. We fetch it from the backend
      // once — no need to hardcode secrets in the CLI, and the anon key
      // is safe to expose by design.
      const authConfigRes = await fetch(`${cfg.api_base}/api/cli/auth-config`);
      if (!authConfigRes.ok) return false;
      const { supabase_url, supabase_anon_key } = (await authConfigRes.json()) as {
        supabase_url: string;
        supabase_anon_key: string;
      };

      const res = await fetch(
        `${supabase_url}/auth/v1/token?grant_type=refresh_token`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            apikey: supabase_anon_key,
          },
          body: JSON.stringify({ refresh_token: cfg.refresh_token }),
        },
      );
      if (!res.ok) return false;
      const body = (await res.json()) as {
        access_token?: string;
        refresh_token?: string;
        expires_at?: number;
      };
      if (!body.access_token) return false;

      writeConfig({
        ...cfg,
        access_token: body.access_token,
        refresh_token: body.refresh_token ?? cfg.refresh_token,
        expires_at: body.expires_at ?? cfg.expires_at,
      });
      return true;
    } catch {
      return false;
    } finally {
      _refreshInFlight = null;
    }
  })();
  return _refreshInFlight;
}

// ── Auth ────────────────────────────────────────────────────────────

export async function deviceStart(
  hostname: string,
  os: string,
): Promise<{
  request_id: string;
  device_code: string;
  verification_url: string;
  interval: number;
  expires_in: number;
}> {
  return apiFetch("/api/cli/auth/device/start", {
    method: "POST",
    auth: false,
    body: JSON.stringify({ hostname, os }),
  });
}

export interface DevicePollResult {
  status: "authorized" | "pending" | "denied" | "expired";
  tokens?: {
    access_token: string;
    refresh_token: string;
    expires_at: number;
    user: { id: string; email: string };
  };
}

/** Polls the token endpoint once. Maps HTTP status → poll status.
 *  Uses a raw fetch so 428/403/410 aren't thrown as errors. */
export async function devicePoll(deviceCode: string): Promise<DevicePollResult> {
  const cfg = readConfig();
  const res = await fetch(`${cfg.api_base}/api/cli/auth/device/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_code: deviceCode }),
  });
  if (res.status === 200) return { status: "authorized", tokens: await res.json() };
  if (res.status === 428) return { status: "pending" };
  if (res.status === 403) return { status: "denied" };
  return { status: "expired" };
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

// ── Briefings ────────────────────────────────────────────────────────

export type BriefingSectionStatus = "auto" | "pinned" | "hybrid";
export type BriefingProvenance = "auto" | "user_ui" | "agent_mcp";

export interface BriefingSection<C = unknown> {
  status: BriefingSectionStatus;
  content: C;
  provenance: BriefingProvenance;
  updated_at: string;
  updated_by: string | null;
}

export interface BriefingResponse {
  folder: { id: string; name: string; kind?: "folder" | "repo" };
  schema_version: number;
  sections: Record<string, BriefingSection>;
  last_generated_at: string | null;
}

export async function fetchBriefing(folderId: string): Promise<BriefingResponse> {
  return apiFetch(`/api/folders/${folderId}/briefing`);
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

/**
 * Step 1 of the private-repo deploy-key flow. Backend generates a
 * keypair, stores the private encrypted, returns the public plus a
 * ready-to-paste `gh` command for manual install.
 */
export async function prepareGithubClone(args: {
  root_folder_id: string;
  repo_url: string;
  since_days?: number;
}): Promise<{
  config_id: string;
  public_key: string;
  manual_setup_hint: string;
}> {
  return apiFetch<{
    config_id: string;
    public_key: string;
    manual_setup_hint: string;
  }>("/api/github/prepare-clone", {
    method: "POST",
    body: JSON.stringify({ since_days: 30, ...args }),
  });
}

/**
 * Step 2 of the deploy-key flow. Backend attempts an SSH clone using
 * the previously-stored private key. Fails cleanly if the public key
 * wasn't installed on the repo.
 */
export async function finalizeGithubClone(args: {
  config_id: string;
}): Promise<unknown> {
  return apiFetch("/api/github/finalize-clone", {
    method: "POST",
    body: JSON.stringify(args),
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
