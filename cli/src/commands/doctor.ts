/**
 * `agentic-rag doctor` — health checks + fix suggestions.
 *
 * Runs a sequence of probes end-to-end so a broken install is fast to
 * diagnose:
 *   1. Config file exists + readable
 *   2. Backend reachable at api_base
 *   3. Login token still valid (whoami)
 *   4. MCP SSE endpoint reachable
 *   5. `gh` CLI status (optional but nice to know)
 *   6. Per-repo binding files (.mcp.json / hook / state / CLAUDE.md)
 *
 * Every failure prints a one-line fix.
 */

import { existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";
import kleur from "kleur";
import { readConfig } from "../lib/config.js";
import { section, info } from "../lib/banner.js";
import { detectGit } from "../lib/git.js";

type CheckResult = { name: string; ok: boolean; detail?: string; hint?: string };

async function timedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 3000);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

export async function doctor(): Promise<void> {
  const cfg = readConfig();
  const checks: CheckResult[] = [];

  // 1. Config
  const configPresent = !!cfg.access_token && !!cfg.email;
  checks.push({
    name: "Config file",
    ok: configPresent,
    detail: configPresent ? `Signed in as ${cfg.email}` : "No token stored",
    hint: configPresent ? undefined : "Run: agentic-rag login",
  });

  // 2. Backend reachable
  let backendOk = false;
  let backendDetail = "";
  try {
    const r = await timedFetch(`${cfg.api_base}/api/health`);
    backendOk = r.status === 200;
    backendDetail = `${cfg.api_base} (HTTP ${r.status})`;
  } catch (err) {
    backendDetail = err instanceof Error ? err.message : String(err);
  }
  checks.push({
    name: "Backend reachable",
    ok: backendOk,
    detail: backendDetail,
    hint: backendOk
      ? undefined
      : `Backend not responding. Start it, or set AGENTIC_RAG_API_BASE. Current: ${cfg.api_base}`,
  });

  // 3. Login token valid — only if config + backend both work
  if (configPresent && backendOk) {
    try {
      const r = await timedFetch(`${cfg.api_base}/api/cli/whoami`, {
        headers: { Authorization: `Bearer ${cfg.access_token}` },
      });
      if (r.status === 200) {
        const body = (await r.json()) as { root_folders?: unknown[] };
        checks.push({
          name: "Login token",
          ok: true,
          detail: `${(body.root_folders ?? []).length} root folder(s) visible`,
        });
      } else {
        checks.push({
          name: "Login token",
          ok: false,
          detail: `Backend returned ${r.status}`,
          hint: "Session expired. Run: agentic-rag login",
        });
      }
    } catch (err) {
      checks.push({
        name: "Login token",
        ok: false,
        detail: err instanceof Error ? err.message : String(err),
      });
    }
  }

  // 4. MCP reachable — derive URL from backend
  const mcpUrl =
    process.env.AGENTIC_RAG_MCP_URL ??
    cfg.api_base.replace(/:8000\b/, ":8001").replace(/\/api$/, "") +
      "/health";
  try {
    const r = await timedFetch(mcpUrl.replace(/\/sse$/, "/health"));
    checks.push({
      name: "MCP server reachable",
      ok: r.status === 200,
      detail: mcpUrl.replace(/\/health$/, ""),
      hint:
        r.status === 200
          ? undefined
          : "MCP server not responding. Start it, or set AGENTIC_RAG_MCP_URL.",
    });
  } catch (err) {
    checks.push({
      name: "MCP server reachable",
      ok: false,
      detail: err instanceof Error ? err.message : String(err),
      hint: "MCP server not responding on the derived URL. Set AGENTIC_RAG_MCP_URL to override.",
    });
  }

  // 5. gh CLI status (optional)
  let ghStatus: CheckResult = {
    name: "gh CLI (optional)",
    ok: false,
    detail: "Not installed — private repos will need a PAT.",
    hint: undefined,
  };
  try {
    execFileSync("gh", ["--version"], {
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 2000,
    });
    try {
      execFileSync("gh", ["auth", "token"], {
        stdio: ["ignore", "pipe", "ignore"],
        timeout: 2000,
      });
      ghStatus = { name: "gh CLI (optional)", ok: true, detail: "Installed + authenticated" };
    } catch {
      ghStatus = {
        name: "gh CLI (optional)",
        ok: false,
        detail: "Installed but not authenticated",
        hint: "Run: gh auth login  (silences PAT prompt for private repos)",
      };
    }
  } catch {
    // Not installed — the default detail already covers this
  }
  checks.push(ghStatus);

  // Print system results
  section("System");
  for (const c of checks) print(c);

  // 6. This repo
  section("This repo");
  const repoRoot = resolve(process.cwd());
  const git = detectGit(repoRoot);
  info(
    git.isRepo
      ? `git: ${git.owner ? `${git.owner}/${git.repo}` : "(no remote)"}`
      : "git: not a repo",
  );
  const mcpJson = existsSync(join(repoRoot, ".mcp.json"));
  print({
    name: ".mcp.json",
    ok: mcpJson,
    hint: mcpJson ? undefined : "Run: agentic-rag init",
  });
  const settingsPath = join(repoRoot, ".claude", "settings.json");
  const settingsExists = existsSync(settingsPath);
  print({
    name: ".claude/settings.json",
    ok: settingsExists,
    hint: settingsExists ? undefined : "Run: agentic-rag init",
  });
  const claudeMd = existsSync(join(repoRoot, "CLAUDE.md"));
  print({
    name: "CLAUDE.md",
    ok: claudeMd,
    hint: claudeMd ? undefined : "Run: agentic-rag init",
  });
  const state = existsSync(join(repoRoot, ".claude", "agentic-rag-state.json"));
  print({
    name: ".claude/agentic-rag-state.json",
    ok: state,
    hint: state ? undefined : "Run: agentic-rag init",
  });

  // Summary
  const anyFailed = checks.some((c) => !c.ok && !c.name.includes("optional"));
  const bindingFailed = !mcpJson || !settingsExists || !claudeMd;
  console.log();
  if (anyFailed || bindingFailed) {
    console.log(
      `  ${kleur.yellow("!")} ${kleur.bold("Some checks failed above.")}`,
    );
    console.log(
      `    ${kleur.dim("Follow the fix hints on each line. Re-run `agentic-rag doctor` when done.")}`,
    );
  } else {
    console.log(
      `  ${kleur.green("✓")} ${kleur.bold("All checks passed.")}${kleur.dim("  Open Claude Code here — you're set.")}`,
    );
  }
  console.log();
}

function print(c: CheckResult): void {
  const icon = c.ok ? kleur.green("✓") : kleur.red("✗");
  const label = c.name.padEnd(30);
  const detail = c.detail ? `  ${kleur.dim(c.detail)}` : "";
  console.log(`  ${icon} ${label}${detail}`);
  if (!c.ok && c.hint) {
    console.log(`    ${kleur.dim(c.hint)}`);
  }
}
