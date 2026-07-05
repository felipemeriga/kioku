/**
 * `agentic-rag search "query"` — knowledge-base search from the terminal.
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
      const bearer = mcp.mcpServers?.["agentic-rag"]?.headers?.Authorization;
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
      "cd into a repo with .mcp.json, or run `agentic-rag init` first.",
    );
    process.exitCode = 1;
    return;
  } else {
    warn(
      "Not signed in and no .mcp.json here.",
      "Run: agentic-rag login  (or cd into a wired repo)",
    );
    process.exitCode = 1;
    return;
  }

  const base = cfg.api_base;
  const res = await fetch(`${base}/api/cli/search`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
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
  for (let i = 0; i < data.hits.length; i += 1) {
    const h = data.hits[i];
    const sim = (h.similarity * 100).toFixed(0);
    const badge = sourceBadge(h.source);
    const title = h.filename ? kleur.cyan(h.filename) : kleur.dim("(no file)");
    const category = h.category ? kleur.dim(" · " + h.category) : "";
    console.log(
      `  ${kleur.bold(`${i + 1}.`)}  ${badge}  ${title}${category}  ${kleur.dim(sim + "%")}`,
    );
    // Truncated snippet with dim wrapping
    const snippet = h.content
      .split("\n")
      .filter((l) => l.trim())
      .slice(0, 5)
      .join("\n");
    for (const line of snippet.split("\n")) {
      console.log("       " + kleur.dim(line.trim().slice(0, 100)));
    }
    console.log();
  }
}

function sourceBadge(s: string): string {
  const label = s.padEnd(12);
  if (s === "docs") return kleur.bgMagenta(kleur.black(" docs   "));
  if (s === "mem0_eternal") return kleur.bgYellow(kleur.black(" preference "));
  if (s === "mem0_episodic") return kleur.bgCyan(kleur.black(" memory "));
  return kleur.dim(label);
}
