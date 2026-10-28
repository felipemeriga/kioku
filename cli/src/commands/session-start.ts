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
  const activeSections = sectionOrder.filter(
    (section) => section !== "preferences",
  );
  // A single MCP key can span several repos (the Codex surface uses one global
  // key scoped to the whole root), so every WRITE must name THIS repo. `folder`
  // is this repo's folder id/name; thread it into the write calls below.
  const f = folder ? `, folder="${folder}"` : "";
  const folderNote = folder
    ? [
        "",
        `IMPORTANT: your MCP key may span several repos, so pass folder="${folder}"`,
        "on every write call below (replace_folder_briefing, save_repo_documentation)",
        "so the briefing lands on THIS repo and not a sibling.",
      ]
    : [];
  return [
    "Generate practical Kioku knowledge for THIS repository: a descriptive",
    "briefing for session starts and a focused architecture/operations document.",
    "Ground both in real code. Help a developer understand and work in this",
    "repo quickly; do not write an exhaustive research report.",
    ...folderNote,
    "",
    "Do this:",
    "1. Call the `get_folder_briefing_schema` MCP tool to get the exact expected",
    "   shape + authoring notes for each section.",
    "2. Call the `read_folder_documents` MCP tool once. Use uploaded documents",
    "   only where they clarify this repo's behavior or a direct interface it",
    "   implements. Prefer current source when docs conflict. Do not expand into",
    "   a tour of parent-folder systems or reproduce documents wholesale.",
    "3. Explore entry points, owned components, data flow, run commands, and",
    "   deployment. Find code with Kioku `code_search` (semantic search), graph",
    "   tools (`outline`, `find_definition`, `find_references`, `impact_of`),",
    "   or your normal local search/grep tool (such as `rg`). Use whichever",
    "   gives the clearest path; you do not need to call every tool. When a",
    "   result is missing, stale, contradictory, or uncertain, compare it with",
    "   current local source using grep or another independent search method.",
    "   For a large repo, parallelize distinct areas, then synthesize briefly.",
    `4. Write these ${activeSections.length} descriptive sections, grounded in the`,
    `   actual code with REAL file paths, following the schema shapes: ${activeSections.join(
      ", ",
    )}.`,
    "   Keep each section focused on what a developer needs at session start:",
    "   purpose, responsibilities, key paths, and actionable commands. Explain",
    "   why the important pieces matter instead of merely naming them.",
    "   Give architecture a concrete component map and data flow; give",
    "   deployment the real environments and release path. Inspect tracked",
    "   `.github/workflows/` files, release scripts, and deploy manifests before",
    "   writing deployment or CI claims. State verified triggers, jobs, image",
    "   build/publish steps, and deploy targets with their source paths. If the",
    "   repository has no evidence for a step, omit it; do not infer a pipeline.",
    "   Use short, readable prose; avoid repeating the same fact across sections.",
    "   In `how_it_runs`, be useful to a developer opening this repo for the",
    "   first time. Explain prerequisites and why they matter; give the real",
    "   setup, start, and test commands for every distinct supported run mode",
    "   (for example local development, containers, CLI, workers, and tests)",
    "   and the order they run. Use short headed paragraphs, not a compressed",
    "   semicolon-separated command dump. For a large repo, cover the important",
    "   run modes and packages without repeating every script. Do not invent",
    "   commands or secret values; state when the repo does not document a step.",
    "5. ALSO fill the `activity` section so the web UI shows it — make it",
    "   genuinely useful, not a one-liner. Read a good chunk of history",
    "   (`git log` for roughly the last ~30-50 commits or ~2-3 months) and write:",
    "     - `summary` = a 4-8 sentence NARRATIVE of the themes and direction of",
    "       recent work (what areas are moving, what's being built/fixed/refactored).",
    "     - `highlights` = 5-10 concrete bullets, each a notable change/feature/fix",
    "       with a bit of context (what and why; reference PR numbers when visible).",
    "   Group related commits into themes; do NOT paste a raw commit list. (Claude",
    "   Code sessions still get live git activity separately — this is the stored",
    "   web-UI section.)",
    "6. Save the briefing sections + activity in ONE call to",
    `   \`replace_folder_briefing(sections=<json>, pin_all=False${f})\` — a JSON object mapping`,
    "   each section name to its content.",
    "   These generated sections stay available for Mihari to review and update",
    "   after new commits. Pin only deliberate manual edits made later.",
    "7. Then produce a focused markdown architecture/operations document for",
    "   this repository. Cover its purpose and boundaries, owned subsystems and",
    "   their responsibilities, main data/control flow, key paths, how to run",
    "   and test it, deployment/CI, and a few important gotchas. For a large",
    "   repo aim for about 800–1,200 words; use less for a small repo. Ground",
    "   architecture and detailed explanations in retrieved code or documents,",
    "   checking uncertain claims against current source. Explain the important",
    "   mechanisms without inventorying every module, commit,",
    "   external service, timestamp, or configuration field. Mention external",
    "   systems only to explain a direct input/output boundary of this repo.",
    "   Do not include a scope/evidence diary (branch, HEAD, sources read, tool",
    "   calls, schema retrieval, caveats about what you did not inspect), long",
    "   historical comparisons, or speculative ecosystem architecture. Put",
    "   short source paths beside claims where useful. Save the document with",
    `   \`save_repo_documentation(content=<the full markdown>, abstract=<a short`,
    `   3–8 line summary>${f})\`. This is the focused reference document.`,
    "",
    "Never invent a fact, command, dependency, or behavior that Kioku or another",
    "search method did not retrieve and that you cannot verify. Omit unsupported",
    "claims. Be clear and concise. Do not ask questions; produce and save",
    "BOTH the briefing (with activity) and the focused documentation.",
  ].join("\n");
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

  const { readLastSessionAt, stampLastSessionAt } = await import(
    "../lib/claude.js"
  );
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
      // Inject the stable sections + the `documentation` abstract (the full
      // deep doc stays out of the prompt — fetched on demand via MCP).
      for (const key of [
        ...s.section_order.filter((key) => key !== "preferences"),
        "documentation",
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
      // Deep-doc offer — only once the concise summary already exists, so a
      // fresh repo isn't asked for an expensive scan on its first session.
      if (s.doc_needs_generation) {
        console.log(
          "\nThis repo's deep documentation is missing or over 30 days old. When you're " +
            'ready, say "generate the docs" and I\'ll scan the repository — fanning out ' +
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
