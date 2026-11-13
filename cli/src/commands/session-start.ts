/**
 * Print a compact briefing to stdout — Claude Code appends it to the
 * initial session context via the SessionStart hook.
 *
 * Reads the .mcp.json in the current repo to find the API key. Falls
 * back to a friendly message if the CLI hasn't been initialized here.
 */

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { mcpUrlToRestBase } from "../lib/urls.js";

async function fetchJson(url: string, headers: Record<string, string>) {
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

/** The detailed generation instruction. `kioku init` hands it to a freshly
 *  launched interactive Claude Code session as its first task; the SessionStart
 *  hook injects it into a session that opens without a briefing. Grounded,
 *  process-oriented, and points at the schema tool so per-section shapes stay
 *  defined in one place (the backend). */
export function generateInstruction(
  sectionOrder: string[],
  folder?: string,
): string {
  const keys = [
    "overview",
    "architecture",
    "how_it_runs",
    "deployment",
    "activity",
  ];
  const activeSections = keys.filter((section) =>
    sectionOrder.includes(section),
  );
  const f = folder ? `, folder="${folder}"` : "";
  const folderNote = folder
    ? `Pass folder="${folder}" on every write so it lands on THIS repository.`
    : "";
  return [
    "Generate a concise Kioku briefing for THIS repository, grounded in current code.",
    "Its five sections are Introduction, Components, How it runs, Deployment, and Activity.",
    folderNote,
    "1. Call `get_folder_briefing_schema` for the exact shapes and authoring notes.",
    "2. Call `read_folder_documents` once for relevant authored reference material.",
    "   Prefer current source when it conflicts with old documentation; do not copy whole documents.",
    "3. Inspect entry points, owned components, commands, tests and deployment files.",
    "   Use `code_search` (semantic search), `outline`, `find_definition`, `find_references`,",
    "   `impact_of`, or your normal local search/grep tool such as `rg`.",
    "   Choose the clearest source; you do not need to call every tool. If an indexed result",
    "   is missing, stale or uncertain, compare it with current local source.",
    `4. Write these sections with real paths: ${activeSections.join(", ")}.`,
    "   overview: one purpose sentence and at most three short description sentences.",
    "   architecture: a concise component map, each component's responsibility and key path.",
    "   Keep its summary and data_flow to one sentence each; avoid a second architecture essay.",
    "   how_it_runs: prerequisites, setup, start and test commands for each distinct supported run mode.",
    "   Use short headings, bullets and fenced commands with brief explanations.",
    "   deployment: inspect `.github/workflows/`, release scripts and deploy manifests before",
    "   describing environments, triggers, release steps or CI. Keep only essential verified facts.",
    "   activity: read recent principal-branch git history, then write two or three short",
    "   sentences and at most five highlights of merged changes. Past investigations belong in History.",
    "   Avoid repeating facts across sections; aim for 600–900 words for the complete briefing.",
    "5. Save the sections in ONE call:",
    `   \`replace_folder_briefing(sections=<json>, pin_all=False${f})\``,
    "   These generated sections remain available for Mihari maintenance after new commits.",
    "   Preserve deliberate user edits; do not pin automatically generated content.",
    "Never invent a fact, command, dependency or behavior. Omit unsupported claims.",
    "Do not ask questions; produce and save the five-section briefing.",
  ]
    .filter(Boolean)
    .join("\n");
}

/** Resolve the kioku API key + MCP url for this session, agent-neutrally.
 *  Prefer the Claude surface (.mcp.json in the repo); fall back to the Codex
 *  surface (the global ~/.codex/config.toml). Returns null if neither is wired,
 *  so the hook can exit silently in a non-kioku session. */
function resolveKeyAndUrl(
  repoRoot: string,
): { apiKey: string; mcpUrl: string } | null {
  const mcpPath = join(repoRoot, ".mcp.json");
  if (existsSync(mcpPath)) {
    try {
      const cfg = JSON.parse(readFileSync(mcpPath, "utf8")) as {
        mcpServers?: Record<
          string,
          { url?: string; headers?: Record<string, string> }
        >;
      };
      const entry = cfg.mcpServers?.["kioku"];
      const auth = entry?.headers?.Authorization;
      if (auth && entry?.url) {
        return { apiKey: auth.replace(/^Bearer\s+/, ""), mcpUrl: entry.url };
      }
    } catch {
      /* fall through to the Codex surface */
    }
  }
  return null;
}

export async function sessionStart(): Promise<void> {
  const repoRoot = resolve(process.cwd());

  let resolved = resolveKeyAndUrl(repoRoot);
  if (!resolved) {
    // No Claude .mcp.json — try the global Codex config.
    const { readCodexMcpEntry } = await import("../lib/codex.js");
    const codex = readCodexMcpEntry();
    if (codex) resolved = { apiKey: codex.key, mcpUrl: codex.entry.url };
  }
  // Silently exit — no complaint, since the hook fires everywhere including in
  // projects/sessions that never opted in.
  if (!resolved) return;
  const { apiKey, mcpUrl } = resolved;

  // Derive the REST API base from the MCP URL (dev ports + prod subdomains).
  // Convention: MCP is at /sse; REST is at /api on the derived base.
  const base = mcpUrlToRestBase(mcpUrl);

  // The CLI's session-start uses the api-key against a lightweight REST
  // endpoint that returns exactly what the coding agent needs, without
  // establishing a full MCP session (which is slower and heavier).
  const H = { Authorization: `Bearer ${apiKey}` };

  // Which folder is this repo bound to? init wrote it to kioku-state.json.
  let folderId: string | undefined;
  try {
    const st = JSON.parse(
      readFileSync(join(repoRoot, ".claude", "kioku-state.json"), "utf8"),
    ) as { folder_id?: string };
    folderId = st.folder_id;
  } catch {
    /* not wired to a folder — nothing to inject */
  }
  if (!folderId) return;

  const { readLastSessionAt, stampLastSessionAt } =
    await import("../lib/claude.js");
  const { composeActivity } = await import("../lib/git-activity.js");

  try {
    const s = (await fetchJson(
      `${base}/api/cli/folder-summary?folder_id=${encodeURIComponent(
        folderId,
      )}`,
      H,
    )) as {
      needs_generation: boolean;
      sections: Record<string, { content: unknown }> | null;
      section_order: string[];
      doc_needs_generation?: boolean;
    };

    console.log("── kioku second-brain ──");
    if (s.needs_generation) {
      if (process.env.KIOKU_NO_AUTOGEN) {
        // A launcher (e.g. `kioku init`) already handed this session the
        // generation instruction as its first task — don't duplicate it here.
        console.log(
          "This repo has no kioku briefing yet — generating it now as the first task.",
        );
      } else {
        // No background/detached generation: make it the session's FIRST task by
        // injecting the instruction as context, so the summary + activity + deep
        // doc are produced in this session before anything else.
        console.log(
          "This repo has no kioku briefing yet. Generate it now as your FIRST " +
            "task, before responding to anything else:\n",
        );
        console.log(generateInstruction(s.section_order, folderId));
      }
    } else if (s.sections) {
      // Only the concise five-section briefing belongs in startup context.
      for (const key of [
        "overview",
        "architecture",
        "how_it_runs",
        "deployment",
        "activity",
      ]) {
        const sec = s.sections[key];
        if (!sec) continue;
        const body =
          typeof sec.content === "string"
            ? sec.content
            : JSON.stringify(sec.content, null, 2);
        if (
          !body ||
          !body.trim() ||
          body.trim() === "{}" ||
          body.trim() === '""'
        )
          continue;
        console.log(`\n## ${key}\n${body}`);
      }
    }

    // Live git activity — always injected when the repo is a clone, no LLM.
    const since = readLastSessionAt(repoRoot);
    const activity = composeActivity(repoRoot, since);
    if (activity) console.log("\n" + activity);
    stampLastSessionAt(repoRoot, new Date().toISOString());

    console.log("─────────────────────────────────");
  } catch (err) {
    // This runs on EVERY Claude Code session start, so a self-hoster whose
    // backend is momentarily down would otherwise see a cryptic "fetch failed"
    // each time. Give the common unreachable case a clear, reassuring message;
    // always exit cleanly so the hook never disrupts the session.
    const msg = err instanceof Error ? err.message : String(err);
    const unreachable =
      /fetch failed|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|getaddrinfo|network|timed? ?out/i.test(
        msg,
      );
    console.error(
      unreachable
        ? "kioku: backend unreachable — skipping briefing this session (your session is unaffected)."
        : `kioku: ${msg}`,
    );
  }
}
