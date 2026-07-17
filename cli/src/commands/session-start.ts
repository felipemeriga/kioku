/**
 * Print a compact briefing to stdout — Claude Code appends it to the
 * initial session context via the SessionStart hook.
 *
 * Reads the .mcp.json in the current repo to find the API key. Falls
 * back to a friendly message if the CLI hasn't been initialized here.
 */

import { existsSync, readFileSync, writeFileSync, statSync, openSync } from "node:fs";
import { join, resolve } from "node:path";
import { spawn } from "node:child_process";

async function fetchJson(url: string, headers: Record<string, string>) {
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

type AutogenStatus = "launched" | "pending" | "unavailable";

/**
 * Kick off a DETACHED, headless `claude -p` that generates this repo's summary
 * in the background (on the user's subscription, via MCP) when none exists —
 * so the summary is produced automatically without the user prompting and
 * without hijacking the interactive session.
 *
 * Guards:
 *  - KIOKU_NO_AUTOGEN (set on the spawned child) prevents infinite recursion:
 *    the background `claude` also runs this SessionStart hook, but must NOT
 *    spawn another generator.
 *  - a debounce lock (.claude/kioku-autogen.lock, 30 min) stops repeated
 *    launches across sessions.
 *  - bypassPermissions so the unattended run doesn't block on tool prompts.
 */
function maybeAutogenSummary(repoRoot: string, sectionOrder: string[]): AutogenStatus {
  if (process.env.KIOKU_NO_AUTOGEN) return "unavailable"; // recursion guard
  const lockPath = join(repoRoot, ".claude", "kioku-autogen.lock");
  const DEBOUNCE_MS = 30 * 60 * 1000;
  try {
    if (existsSync(lockPath) && Date.now() - statSync(lockPath).mtimeMs < DEBOUNCE_MS) {
      return "pending"; // a recent run is (or was) in flight
    }
  } catch {
    /* ignore */
  }
  const prompt =
    "Generate this repository's kioku briefing now. Read the repo (fan out " +
    "subagents if helpful) and write these sections concisely: " +
    `${sectionOrder.join(", ")}. Then save them by calling the ` +
    "replace_folder_briefing MCP tool for this folder. Do not ask questions — " +
    "just produce and save the briefing.";
  try {
    writeFileSync(lockPath, new Date().toISOString() + "\n");
    const logFd = openSync(join(repoRoot, ".claude", "kioku-autogen.log"), "a");
    const child = spawn(
      "claude",
      ["-p", prompt, "--permission-mode", "bypassPermissions"],
      {
        cwd: repoRoot,
        env: { ...process.env, KIOKU_NO_AUTOGEN: "1" },
        detached: true,
        stdio: ["ignore", logFd, logFd],
      },
    );
    child.unref();
    return "launched";
  } catch {
    return "unavailable"; // `claude` CLI missing or spawn failed
  }
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
      // Auto-generate in the background so it happens without prompting. The
      // spawned `claude` (KIOKU_NO_AUTOGEN=1) falls into the "unavailable"
      // branch below and gets the write-instruction as its actual task.
      const status = maybeAutogenSummary(repoRoot, s.section_order);
      if (status === "launched" || status === "pending") {
        console.log(
          "This repo has no summary yet — kioku is generating one in the background " +
            "(scanning the repo on your Claude subscription). It'll appear next session.",
        );
      } else {
        console.log(
          "This repo has no current summary. Please read the repository and write these " +
            `sections: ${s.section_order.join(", ")}. Then save them by calling the ` +
            "`replace_folder_briefing` MCP tool for this folder. Keep each section concise.",
        );
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
    console.error(`kioku: ${err instanceof Error ? err.message : String(err)}`);
  }
}
