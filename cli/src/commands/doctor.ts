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

import { existsSync, readFileSync } from "node:fs";
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
  // Validate that the .mcp.json api key actually AUTHENTICATES — file
  // existence isn't enough. A key can be revoked (re-initing a sibling repo
  // under the same scope, or from the UI) while the file stays put; then
  // Claude Code's SessionStart hook + every MCP tool 401 silently. Only flag
  // a confirmed rejection so a missing key/state doesn't double-report.
  let keyRejected = false;
  if (mcpJson) {
    let keyOk = false;
    let keyDetail = "";
    try {
      const mcp = JSON.parse(readFileSync(join(repoRoot, ".mcp.json"), "utf8")) as {
        mcpServers?: Record<string, { headers?: Record<string, string> }>;
      };
      const auth = mcp.mcpServers?.["kioku"]?.headers?.Authorization;
      let folderId: string | undefined;
      try {
        folderId = (
          JSON.parse(
            readFileSync(join(repoRoot, ".claude", "kioku-state.json"), "utf8"),
          ) as { folder_id?: string }
        ).folder_id;
      } catch {
        /* no state file */
      }
      if (auth && folderId) {
        const r = await timedFetch(
          `${cfg.api_base}/api/cli/folder-summary?folder_id=${encodeURIComponent(folderId)}`,
          { headers: { Authorization: auth } },
        );
        keyOk = r.status === 200;
        keyRejected = r.status === 401 || r.status === 403;
        keyDetail = keyOk ? "authenticates OK" : `rejected (HTTP ${r.status})`;
      } else {
        keyOk = true; // nothing to validate — don't false-alarm
        keyDetail = "skipped (no key or folder_id)";
      }
    } catch (err) {
      keyOk = true; // network/parse error → not a key problem; other checks cover it
      keyDetail = err instanceof Error ? err.message : String(err);
    }
    print({
      name: "API key valid",
      ok: keyOk,
      detail: keyDetail,
      hint: keyRejected ? "Key revoked or invalid — run: kioku init" : undefined,
    });
  }
  // kioku's SessionStart/Stop hooks live in the per-user settings.local.json.
  const localSettingsPath = join(repoRoot, ".claude", "settings.local.json");
  let hookInstalled = false;
  try {
    if (existsSync(localSettingsPath)) {
      const s = JSON.parse(readFileSync(localSettingsPath, "utf8")) as {
        hooks?: { SessionStart?: Array<{ hooks?: Array<{ command?: string }> }> };
      };
      hookInstalled = !!s.hooks?.SessionStart?.some((g) =>
        g.hooks?.some((h) => (h.command ?? "").includes("kioku")),
      );
    }
  } catch {
    /* leave false */
  }
  print({
    name: "SessionStart hook (settings.local.json)",
    ok: hookInstalled,
    hint: hookInstalled ? undefined : "Run: kioku init",
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
  const bindingFailed = !mcpJson || !hookInstalled || !claudeMd || keyRejected;
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
