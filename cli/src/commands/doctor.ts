/**
 * `kioku doctor` — health checks + fix suggestions.
 *
 * Runs a sequence of probes end-to-end so a broken install is fast to
 * diagnose:
 *   1. Config file exists + readable
 *   2. Backend reachable at api_base
 *   3. Login token still valid (whoami)
 *   4. MCP SSE endpoint reachable
 *   5. Per-repo binding files (.mcp.json / hook / state / CLAUDE.md)
 *
 * Every failure prints a one-line fix.
 */

import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import kleur from "kleur";
import { readConfig } from "../lib/config.js";
import { section, info } from "../lib/banner.js";
import { detectGit } from "../lib/git.js";
import { renderTable } from "../ui/table.js";
import { panel } from "../ui/panel.js";
import { sym } from "../ui/theme.js";

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
    hint: configPresent ? undefined : "Run: kioku login",
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
      : `Backend not responding. Start it, or set KIOKU_API_BASE. Current: ${cfg.api_base}`,
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
          hint: "Session expired. Run: kioku login",
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
    process.env.KIOKU_MCP_URL ??
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
          : "MCP server not responding. Start it, or set KIOKU_MCP_URL.",
    });
  } catch (err) {
    checks.push({
      name: "MCP server reachable",
      ok: false,
      detail: err instanceof Error ? err.message : String(err),
      hint: "MCP server not responding on the derived URL. Set KIOKU_MCP_URL to override.",
    });
  }

  // Print system results
  section("System");
  console.log(renderTable(
    ["", "Check", "Detail"],
    checks.map((c) => [c.ok ? sym.ok : sym.bad, c.name, c.detail ?? ""]),
  ));
  for (const c of checks) if (!c.ok && c.hint) console.log(`    ${c.hint}`);

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
    hint: mcpJson ? undefined : "Run: kioku init",
  });
  const settingsPath = join(repoRoot, ".claude", "settings.json");
  const settingsExists = existsSync(settingsPath);
  print({
    name: ".claude/settings.json",
    ok: settingsExists,
    hint: settingsExists ? undefined : "Run: kioku init",
  });
  const claudeMd = existsSync(join(repoRoot, "CLAUDE.md"));
  print({
    name: "CLAUDE.md",
    ok: claudeMd,
    hint: claudeMd ? undefined : "Run: kioku init",
  });
  const state = existsSync(join(repoRoot, ".claude", "kioku-state.json"));
  print({
    name: ".claude/kioku-state.json",
    ok: state,
    hint: state ? undefined : "Run: kioku init",
  });

  // Summary
  const anyFailed = checks.some((c) => !c.ok && !c.name.includes("optional"));
  const bindingFailed = !mcpJson || !settingsExists || !claudeMd;
  console.log();
  if (anyFailed || bindingFailed) {
    console.log(panel({ title: "Result", body: "Some checks failed. Follow the fix hints, then re-run kioku doctor.", tone: "warn" }));
  } else {
    console.log(panel({ title: "Result", body: "All checks passed. Open Claude Code here — you're set.", tone: "success" }));
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
