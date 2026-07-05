/**
 * `agentic-rag open` — jump to the web UI.
 *
 * If run inside a wired repo, opens directly to the folder's detail
 * page. Otherwise opens the root URL. Opens the default browser via
 * the OS's standard 'open' command.
 */

import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";
import { readConfig } from "../lib/config.js";
import { info, warn } from "../lib/banner.js";

interface Opts {
  json?: boolean;
}

export async function openCmd(target: string | undefined, opts: Opts): Promise<void> {
  const cfg = readConfig();
  const webBase = deriveWebUrl(cfg.api_base);

  let url = webBase;
  if (target) {
    // Explicit target — treat as a folder id or path.
    url = `${webBase}/folder/${encodeURIComponent(target)}`;
  } else {
    // Try to find the current repo's folder from state.
    const repoRoot = resolve(process.cwd());
    const statePath = join(repoRoot, ".claude", "agentic-rag-state.json");
    if (existsSync(statePath)) {
      try {
        const state = JSON.parse(readFileSync(statePath, "utf8")) as {
          folder_id?: string;
        };
        if (state.folder_id) {
          url = `${webBase}/folder/${state.folder_id}`;
        }
      } catch {
        // fall back to root
      }
    }
  }

  if (opts.json) {
    console.log(JSON.stringify({ url }, null, 2));
    return;
  }

  info(`Opening ${url}`);
  tryOpenBrowser(url);
}

/**
 * Convert an API base URL into a best-guess web UI URL.
 *   http://localhost:8000       → http://localhost:5173
 *   https://api.example.com     → https://app.example.com (best-effort)
 *   otherwise passthrough
 */
function deriveWebUrl(apiBase: string): string {
  const override = process.env.AGENTIC_RAG_WEB_URL;
  if (override) return override.replace(/\/$/, "");

  // Localhost convention: our vite dev server runs on 5173 (or 5174 in this repo).
  if (/localhost:8000/.test(apiBase)) {
    return apiBase.replace("8000", "5174");
  }
  // 'api.example.com' → 'app.example.com'
  const url = new URL(apiBase);
  if (url.host.startsWith("api.")) {
    url.host = "app." + url.host.slice(4);
    return url.origin;
  }
  // Fall back to same host
  return url.origin;
}

function tryOpenBrowser(url: string): void {
  const cmd =
    process.platform === "darwin"
      ? ["open", url]
      : process.platform === "win32"
      ? ["cmd", "/c", "start", url]
      : ["xdg-open", url];
  try {
    execFileSync(cmd[0], cmd.slice(1), { stdio: "ignore", timeout: 2000 });
  } catch {
    warn("Couldn't open the browser automatically.", `Copy this URL: ${url}`);
  }
}
