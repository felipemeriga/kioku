/**
 * CLI config storage — ~/.config/kioku/config.json (0600).
 *
 * Stores:
 *   - api_base:      backend URL (default http://localhost:8000)
 *   - access_token:  Supabase user JWT (short-lived, ~1h)
 *   - refresh_token: for silent renewal
 *   - user_id, email
 *
 * The scoped api-keys minted for individual repos live in each repo's
 * .mcp.json — not in this global config. That keeps them locked to their
 * project and easy to revoke by deleting the repo binding.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { homedir } from "node:os";
import { join, dirname } from "node:path";

export interface CliConfig {
  api_base: string;
  access_token?: string;
  refresh_token?: string;
  expires_at?: number;
  user_id?: string;
  email?: string;
}

const DEFAULT_API_BASE = "http://localhost:8000";

/**
 * Resolve the API base URL with clear precedence, evaluated LAZILY so
 * env changes made by commander's preAction hook (from --api-base flag)
 * take effect:
 *
 *   1. KIOKU_API_BASE env var — set by --api-base flag or shell
 *   2. api_base persisted in ~/.config/kioku/config.json
 *   3. DEFAULT_API_BASE (localhost:8000)
 *
 * Previously the config-file value ALWAYS won over the env var, which
 * defeated the whole purpose of --api-base as an override.
 */
function resolveApiBase(fromFile: string | undefined): string {
  return process.env.KIOKU_API_BASE || fromFile || DEFAULT_API_BASE;
}

function configDir(): string {
  const xdg = process.env.XDG_CONFIG_HOME;
  return xdg
    ? join(xdg, "kioku")
    : join(homedir(), ".config", "kioku");
}

function configPath(): string {
  return join(configDir(), "config.json");
}

export function readConfig(): CliConfig {
  const p = configPath();
  if (!existsSync(p)) {
    return { api_base: resolveApiBase(undefined) };
  }
  try {
    const raw = readFileSync(p, "utf8");
    const parsed = JSON.parse(raw) as CliConfig;
    return { ...parsed, api_base: resolveApiBase(parsed.api_base) };
  } catch {
    // Corrupted config — start fresh rather than crash.
    return { api_base: resolveApiBase(undefined) };
  }
}

export function writeConfig(cfg: CliConfig): void {
  const dir = configDir();
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true, mode: 0o700 });
  const p = configPath();
  writeFileSync(p, JSON.stringify(cfg, null, 2), { mode: 0o600 });
  try {
    chmodSync(p, 0o600);
  } catch {
    // Best-effort — Windows FS may not support chmod.
  }
}

export function clearAuth(): void {
  const cfg = readConfig();
  delete cfg.access_token;
  delete cfg.refresh_token;
  delete cfg.expires_at;
  delete cfg.user_id;
  delete cfg.email;
  writeConfig(cfg);
}

export function isLoggedIn(): boolean {
  const cfg = readConfig();
  return !!cfg.access_token && !!cfg.user_id;
}
