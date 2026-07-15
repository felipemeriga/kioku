/**
 * `kioku search "query"` — knowledge-base search from the terminal.
 *
 * Uses the current repo's api key from .mcp.json (fast + doesn't
 * need the session token — same auth as the SessionStart hook).
 * Falls back to a signed-in user token if we're not inside a wired repo.
 */

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import kleur from "kleur";
import { readConfig } from "../lib/config.js";
import { info, section, warn } from "../lib/banner.js";
import { renderTable } from "../ui/table.js";
import { withSpinner } from "../ui/spinner.js";

interface Opts {
  json?: boolean;
  limit?: string;
  folder?: string;
}

interface Hit {
  source: string;
  content: string;
  similarity: number;
  filename: string | null;
  category: string | null;
  created_at: string | null;
}

export async function search(query: string, opts: Opts): Promise<void> {
  const cfg = readConfig();
  const repoRoot = resolve(process.cwd());
  const mcpPath = join(repoRoot, ".mcp.json");

  let apiKey: string | undefined;
  let source: "mcp" | "user" = "user";
  if (existsSync(mcpPath)) {
    try {
      const mcp = JSON.parse(readFileSync(mcpPath, "utf8")) as {
        mcpServers?: Record<
          string,
          { headers?: Record<string, string> }
        >;
      };
      const bearer = mcp.mcpServers?.["kioku"]?.headers?.Authorization;
      if (bearer) {
        apiKey = bearer.replace(/^Bearer\s+/, "");
        source = "mcp";
      }
    } catch {
      // fall through
    }
  }

  const limit = Math.max(1, Math.min(25, parseInt(opts.limit || "5", 10) || 5));
  const body = { query, limit, folder_id: opts.folder ?? null };

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) {
    headers["Authorization"] = `Bearer ${apiKey}`;
  } else if (cfg.access_token) {
    // No repo binding → we have to guess a folder. Fall back to the
    // signed-in user token, but the api endpoint requires api-key auth.
    // Better UX: tell the user why we can't proceed.
    warn(
      "This works best from inside a wired repo.",
      "cd into a repo with .mcp.json, or run `kioku init` first.",
    );
    process.exitCode = 1;
    return;
  } else {
    warn(
      "Not signed in and no .mcp.json here.",
      "Run: kioku login  (or cd into a wired repo)",
    );
    process.exitCode = 1;
    return;
  }

  const base = cfg.api_base;
  // In --json mode, skip the spinner entirely so stdout is clean JSON.
  const res = await (opts.json
    ? fetch(`${base}/api/cli/search`, { method: "POST", headers, body: JSON.stringify(body) })
    : withSpinner(`Searching "${query}"`, () =>
        fetch(`${base}/api/cli/search`, { method: "POST", headers, body: JSON.stringify(body) }),
      ));
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  const data = (await res.json()) as {
    query: string;
    folder_id: string;
    hits: Hit[];
  };

  if (opts.json) {
    console.log(JSON.stringify(data, null, 2));
    return;
  }

  section(`Search · "${query}"  ${kleur.dim("(source: " + source + ")")}`);
  if (data.hits.length === 0) {
    info("No results.");
    console.log();
    return;
  }
  const rows = data.hits.map((h, i) => [
    String(i + 1),
    h.source,
    h.filename ?? "(no file)",
    `${(h.similarity * 100).toFixed(0)}%`,
    h.content.split("\n").filter((l) => l.trim())[0]?.trim().slice(0, 60) ?? "",
  ]);
  console.log(renderTable(["#", "Source", "File", "Score", "Snippet"], rows));
  console.log();
}
