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

  constructor(
    msg: string,
    opts: { status?: number; kind?: ApiError["kind"]; hint?: string } = {}
  ) {
    super(msg);
    this.name = "ApiError";
    this.status = opts.status ?? 0;
    this.kind = opts.kind ?? "http";
    this.hint = opts.hint;
  }
}

async function apiFetch<T>(
  path: string,
  init: RequestInit & { auth?: boolean; _retry?: boolean } = {}
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
    if (res.status === 401 && !init._retry && auth && cfg.refresh_token) {
      const refreshed = await tryRefreshToken(
        cfg.access_token,
        init.signal ?? undefined
      );
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
    if (res.status === 401) {
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

/** Refresh only authentication failures; outages must not look like logout. */
let _refreshInFlight: Promise<boolean> | null = null;

async function tryRefreshToken(
  rejectedToken: string | undefined,
  callerSignal?: AbortSignal
): Promise<boolean> {
  if (_refreshInFlight) return _refreshInFlight;
  _refreshInFlight = refreshToken(rejectedToken, callerSignal).finally(() => {
    _refreshInFlight = null;
  });
  return _refreshInFlight;
}

async function refreshToken(
  rejectedToken: string | undefined,
  callerSignal?: AbortSignal
): Promise<boolean> {
  const cfg = readConfig();
  // Another request may already have rotated the stored session.
  if (cfg.access_token && cfg.access_token !== rejectedToken) return true;
  if (!cfg.refresh_token) return false;
  const controller = new AbortController();
  const abort = () => controller.abort();
  const timer = setTimeout(abort, 10_000);
  callerSignal?.addEventListener("abort", abort, { once: true });
  if (callerSignal?.aborted) abort();
  const unavailable = (status = 0) =>
    new ApiError(
      "Couldn't renew your session right now. Your saved login has been kept.",
      {
        status,
        kind: status ? "http" : "unreachable",
        hint: "Check your connection and retry the command. You do not need to log in again unless your session is rejected.",
      }
    );
  try {
    const authConfigRes = await fetch(`${cfg.api_base}/api/cli/auth-config`, {
      signal: controller.signal,
    });
    if (!authConfigRes.ok) throw unavailable(authConfigRes.status);
    const { supabase_url, supabase_anon_key } =
      (await authConfigRes.json()) as {
        supabase_url: string;
        supabase_anon_key: string;
      };
    if (!supabase_url || !supabase_anon_key) throw unavailable(502);
    const res = await fetch(
      `${supabase_url}/auth/v1/token?grant_type=refresh_token`,
      {
        method: "POST",
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          apikey: supabase_anon_key,
        },
        body: JSON.stringify({ refresh_token: cfg.refresh_token }),
      }
    );
    if (!res.ok) {
      const error = (await res.json().catch(() => ({}))) as {
        code?: string;
        error_code?: string;
      };
      const code = error.code ?? error.error_code;
      if (
        (res.status === 400 || res.status === 401 || res.status === 403) &&
        code &&
        [
          "refresh_token_not_found",
          "refresh_token_already_used",
          "session_not_found",
          "session_expired",
          "user_not_found",
          "user_banned",
        ].includes(code)
      )
        return false;
      throw unavailable(res.status);
    }
    const body = (await res.json()) as {
      access_token?: string;
      refresh_token?: string;
      expires_at?: number;
      expires_in?: number;
    };
    if (!body.access_token || !body.refresh_token) throw unavailable(502);
    const latest = readConfig();
    // Never resurrect a logout or overwrite a newer login while refresh was in flight.
    if (latest.refresh_token !== cfg.refresh_token)
      return !!latest.access_token;
    writeConfig({
      ...latest,
      access_token: body.access_token,
      refresh_token: body.refresh_token,
      expires_at:
        body.expires_at ??
        (body.expires_in === undefined
          ? undefined
          : Math.floor(Date.now() / 1000) + body.expires_in),
    });
    return true;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw unavailable();
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener("abort", abort);
  }
}

// ── Auth ────────────────────────────────────────────────────────────

export async function deviceStart(
  hostname: string,
  os: string
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
 *  Uses a raw fetch so 428/403/410 aren't thrown as errors.
 *  429 and 5xx are treated as transient (keep waiting); the outer
 *  login loop is bounded by expires_in so this won't spin forever. */
export async function devicePoll(
  deviceCode: string
): Promise<DevicePollResult> {
  const cfg = readConfig();
  let res: Response;
  try {
    res = await fetch(`${cfg.api_base}/api/cli/auth/device/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_code: deviceCode }),
    });
  } catch {
    // Network/fetch error — keep waiting, don't abort
    return { status: "pending" };
  }
  if (res.status === 200)
    return { status: "authorized", tokens: await res.json() };
  if (res.status === 428) return { status: "pending" };
  if (res.status === 403) return { status: "denied" };
  if (res.status === 410) return { status: "expired" };
  // 429 (rate limit) or any 5xx — transient, keep waiting
  if (res.status === 429 || res.status >= 500) return { status: "pending" };
  // Unexpected status — treat as expired (terminal)
  return { status: "expired" };
}

export async function whoami(signal?: AbortSignal): Promise<{
  user_id: string;
  root_folders: RootFolder[];
}> {
  return apiFetch("/api/cli/whoami", { signal });
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
  parent_id: string | null
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

export async function fetchBriefing(
  folderId: string
): Promise<BriefingResponse> {
  return apiFetch(`/api/folders/${folderId}/briefing`);
}

/** Turn a folder into a repo (or rename it, or both). */
export async function updateFolder(
  id: string,
  updates: { name?: string; kind?: "folder" | "repo" }
): Promise<Folder> {
  return apiFetch(`/api/folders/${id}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
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

export async function registerManabi(body: {
  id: string;
  secret: string;
  name: string;
  platform: string;
  version: string;
}): Promise<{ id: string }> {
  return apiFetch("/api/remotes/register", {
    method: "POST",
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(15_000),
  });
}

export async function ownsRepoBinding(folderId: string): Promise<boolean> {
  const rows = await apiFetch<{ id: string; kind: string }[]>(
    `/api/folders/${encodeURIComponent(folderId)}/breadcrumbs`
  );
  return rows.some((row) => row.id === folderId && row.kind === "repo");
}
