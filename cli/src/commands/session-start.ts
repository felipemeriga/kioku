/**
 * Print a compact briefing to stdout — Claude Code appends it to the
 * initial session context via the SessionStart hook.
 *
 * Reads the .mcp.json in the current repo to find the API key. Falls
 * back to a friendly message if the CLI hasn't been initialized here.
 */

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import kleur from "kleur";

async function fetchJson(url: string, headers: Record<string, string>) {
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export async function sessionStart(): Promise<void> {
  const repoRoot = resolve(process.cwd());
  const mcpPath = join(repoRoot, ".mcp.json");
  if (!existsSync(mcpPath)) {
    // Silently exit — no complaint, since the hook fires everywhere
    // including in projects that never opted in.
    return;
  }
  let apiKey: string | undefined;
  let mcpUrl: string | undefined;
  try {
    const raw = readFileSync(mcpPath, "utf8");
    const cfg = JSON.parse(raw) as {
      mcpServers?: Record<
        string,
        { url?: string; headers?: Record<string, string> }
      >;
    };
    const entry = cfg.mcpServers?.["kioku"];
    if (entry?.headers?.Authorization) {
      apiKey = entry.headers.Authorization.replace(/^Bearer\s+/, "");
    }
    mcpUrl = entry?.url;
  } catch {
    return;
  }
  if (!apiKey || !mcpUrl) return;

  // Derive the REST API base from the MCP URL (same host, port 8000 → 8000).
  // Convention: MCP is at /sse; REST is at /api on the same base.
  const base = new URL(mcpUrl).origin.replace(/:8001$/, ":8000");

  // The CLI's session-start uses the api-key against a lightweight REST
  // endpoint that returns exactly what the coding agent needs, without
  // establishing a full MCP session (which is slower and heavier).
  const H = { Authorization: `Bearer ${apiKey}` };

  try {
    // Discovery: list folders in the api-key's scope
    const scope = (await fetchJson(`${base}/api/cli/scope-info`, H)) as {
      scope_name: string;
      folders: Array<{ name: string; kind: string; path: string; has_summary: boolean }>;
    };
    // Print a compact context block Claude Code will surface at session start
    console.log(kleur.dim("── kioku second-brain ──"));
    console.log(`Scope: ${scope.scope_name}`);
    console.log(`Folders in scope: ${scope.folders.length}`);
    const repos = scope.folders.filter((f) => f.kind === "repo");
    if (repos.length > 0) {
      console.log(
        `Repos: ${repos.map((r) => r.path).join(", ")}`,
      );
    }
    console.log(
      kleur.dim(
        "Tools available: get_folder_briefing, get_folder_orientation, list_folders_in_scope, save_memory, search_memory, knowledge_base_search",
      ),
    );
    console.log(
      kleur.dim("Call get_folder_briefing() to load the 8-section briefing."),
    );
    console.log(kleur.dim("─────────────────────────────────"));
  } catch (err) {
    // Non-fatal — sessions still start, agent just doesn't see the block.
    console.error(
      kleur.dim(`kioku: ${err instanceof Error ? err.message : String(err)}`),
    );
  }
}
