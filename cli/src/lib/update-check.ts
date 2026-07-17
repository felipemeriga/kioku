/**
 * Non-blocking npm-registry check. Runs at most once per 24h and prints
 * a subtle "update available" line at the bottom of stdout AFTER the
 * main command has finished. Zero delay on hot path.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import kleur from "kleur";

const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const PKG_NAME = "kioku";

interface Cache {
  checked_at: number;
  latest_version: string | null;
}

function cachePath(): string {
  const xdg = process.env.XDG_CACHE_HOME;
  const dir = xdg
    ? join(xdg, "kioku")
    : join(homedir(), ".cache", "kioku");
  return join(dir, "update-check.json");
}

function readCache(): Cache | null {
  const p = cachePath();
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, "utf8")) as Cache;
  } catch {
    return null;
  }
}

function writeCache(c: Cache): void {
  const p = cachePath();
  const dir = p.slice(0, p.lastIndexOf("/"));
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
  writeFileSync(p, JSON.stringify(c));
}

/**
 * Fire-and-forget check. Call at end of process to avoid delaying
 * anything the user is waiting on.
 */
export async function checkForUpdate(currentVersion: string): Promise<void> {
  if (process.env.KIOKU_NO_UPDATE_CHECK) return;
  const cached = readCache();
  const now = Date.now();
  if (cached && now - cached.checked_at < CACHE_TTL_MS) {
    // Use cached result — still notify but don't hit the network.
    maybeNotify(currentVersion, cached.latest_version);
    return;
  }
  try {
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 2000);
    const res = await fetch(`https://registry.npmjs.org/${PKG_NAME}/latest`, {
      signal: ctrl.signal,
      headers: { Accept: "application/json" },
    });
    clearTimeout(timeout);
    if (!res.ok) return;
    const body = (await res.json()) as { version?: string };
    const latest = body.version ?? null;
    writeCache({ checked_at: now, latest_version: latest });
    maybeNotify(currentVersion, latest);
  } catch {
    // Silent — the check must never block or annoy.
  }
}

function maybeNotify(current: string, latest: string | null): void {
  if (!latest) return;
  if (compareSemver(latest, current) <= 0) return;
  // Subtle bottom-of-output line. Skip if quiet.
  if (process.env.KIOKU_QUIET) return;
  // Only for an interactive terminal — otherwise this stdout line corrupts
  // machine-readable output (e.g. `kioku search --json | jq`, or any piped /
  // redirected command). Non-TTY consumers must get clean stdout.
  if (!process.stdout.isTTY) return;
  console.log();
  console.log(
    `  ${kleur.yellow("⇧")} ${kleur.dim(
      `Update available: ${current} → ${latest}. Run: npm install -g ${PKG_NAME}`,
    )}`,
  );
}

/** Rough semver compare. Returns positive if a > b, 0 if equal, negative if a < b. */
function compareSemver(a: string, b: string): number {
  const pa = a.split(/[.\-+]/).map((x) => parseInt(x, 10) || 0);
  const pb = b.split(/[.\-+]/).map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}
