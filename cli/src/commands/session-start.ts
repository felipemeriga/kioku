/**
 * Print a compact briefing to stdout — Claude Code appends it to the
 * initial session context via the SessionStart hook.
 *
 * Reads the .mcp.json in the current repo to find the API key. Falls
 * back to a friendly message if the CLI hasn't been initialized here.
 */

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

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
export function generateInstruction(sectionOrder: string[]): string {
  return [
    "Generate the COMPLETE kioku knowledge for THIS repository: the concise",
    "briefing AND a detailed architecture document. Both are grounded in the",
    "real code (not generic) and injected/available in future Claude Code",
    "sessions here, so accuracy matters.",
    "",
    "Do this:",
    "1. Call the `get_folder_briefing_schema` MCP tool to get the exact expected",
    "   shape + authoring notes for each section.",
    "2. Explore the repository thoroughly. Fan out subagents in parallel to cover",
    "   distinct areas: entry points & configuration; the core components/modules",
    "   and their responsibilities; data flow and key control paths; how it",
    "   builds/runs/tests; and how it deploys (CI/CD). Reuse this exploration for",
    "   both the briefing and the detailed doc below.",
    `3. Write these ${sectionOrder.length} concise sections, each grounded in the`,
    `   actual code with REAL file paths, following the schema shapes: ${sectionOrder.join(", ")}.`,
    "4. ALSO fill the `activity` section so the web UI shows it — make it",
    "   genuinely useful, not a one-liner. Read a good chunk of history",
    "   (`git log` for roughly the last ~30-50 commits or ~2-3 months) and write:",
    "     - `summary` = a 4-8 sentence NARRATIVE of the themes and direction of",
    "       recent work (what areas are moving, what's being built/fixed/refactored).",
    "     - `highlights` = 5-10 concrete bullets, each a notable change/feature/fix",
    "       with a bit of context (what and why; reference PR numbers when visible).",
    "   Group related commits into themes; do NOT paste a raw commit list. (Claude",
    "   Code sessions still get live git activity separately — this is the stored",
    "   web-UI section.)",
    "5. Save the concise sections + activity in ONE call to",
    "   `replace_folder_briefing` — a JSON object mapping each section name to its",
    "   content.",
    "6. Then produce the DETAILED documentation — a comprehensive, structured",
    "   markdown architecture document: a COMPLETE overview of the whole repo",
    "   (purpose; subsystems/crates and their responsibilities; data & control",
    "   flows; key files with their roles; build/run/test; deployment & CI; and",
    "   notable risks/gotchas), grounded in REAL file paths. Save it with",
    "   `save_repo_documentation(content=<the full markdown>, abstract=<a short",
    "   3–8 line summary>)`. This is the 'complete overview' large document.",
    "",
    "Be dense and grounded. Do not ask questions; produce and save BOTH the",
    "briefing (with activity) and the detailed documentation.",
  ].join("\n");
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

  const { readLastSessionAt, stampLastSessionAt } = await import("../lib/claude.js");
  const { composeActivity } = await import("../lib/git-activity.js");

  try {
    const s = (await fetchJson(
      `${base}/api/cli/folder-summary?folder_id=${encodeURIComponent(folderId)}`,
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
        console.log(generateInstruction(s.section_order));
      }
    } else if (s.sections) {
      // Inject the stable sections + the `documentation` abstract (the full
      // deep doc stays out of the prompt — fetched on demand via MCP).
      for (const key of [...s.section_order, "documentation"]) {
        const sec = s.sections[key];
        if (!sec) continue;
        const body =
          typeof sec.content === "string"
            ? sec.content
            : JSON.stringify(sec.content, null, 2);
        if (!body || !body.trim() || body.trim() === "{}" || body.trim() === '""') continue;
        console.log(`\n## ${key}\n${body}`);
      }
      // Deep-doc offer — only once the concise summary already exists, so a
      // fresh repo isn't asked for an expensive scan on its first session.
      if (s.doc_needs_generation) {
        console.log(
          "\nThis repo's deep documentation is missing or over 30 days old. When you're " +
            "ready, say \"generate the docs\" and I'll scan the repository — fanning out " +
            "subagents across its main areas — write a structured architecture document, " +
            "and save it via the `save_repo_documentation` MCP tool.",
        );
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
      /fetch failed|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|getaddrinfo|network|timed? ?out/i.test(msg);
    console.error(
      unreachable
        ? "kioku: backend unreachable — skipping briefing this session (your session is unaffected)."
        : `kioku: ${msg}`,
    );
  }
}
