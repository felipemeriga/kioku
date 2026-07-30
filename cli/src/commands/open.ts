/**
 * `kioku open` — jump to the web UI.
 *
 * If run inside a wired repo, opens directly to the folder's detail
 * page. Otherwise opens the root URL. Opens the default browser via
 * the OS's standard 'open' command.
 */

import { existsSync, readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";
import { readConfig } from "../lib/config.js";
import { restBaseToWebUrl } from "../lib/urls.js";
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
    const statePath = join(repoRoot, ".claude", "kioku-state.json");
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
 * Convert an API base URL into the web UI URL (KIOKU_WEB_URL overrides).
 *   http://localhost:8000        → http://localhost:5174
 *   https://kioku.api.merigafy.com → https://kioku.merigafy.com
 */
function deriveWebUrl(apiBase: string): string {
  const override = process.env.KIOKU_WEB_URL;
  if (override) return override.replace(/\/$/, "");
  // dev: :8000 → :5174 · prod: <s>.api.<domain> → <s>.<domain>
  return restBaseToWebUrl(apiBase);
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
