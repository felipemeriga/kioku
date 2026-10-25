import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { configDir, readConfig } from "../lib/config.js";
import { whoami } from "../lib/api.js";
import { detectGit } from "../lib/git.js";
import { bad, info, ok, section, warn } from "../lib/banner.js";
import { panel } from "../ui/panel.js";

export async function status(): Promise<void> {
  const cfg = readConfig();

  const lines = [
    `API      ${cfg.api_base}`,
    cfg.access_token ? `Account  ${cfg.email}` : "Account  not signed in",
  ];
  try {
    const status = JSON.parse(
      readFileSync(join(configDir(), "manabi", "status.json"), "utf8")
    );
    lines.push(`Manabi   ${status.code} (last observed ${status.observed_at})`);
    for (const warning of status.warnings ?? [])
      lines.push(`Warning  ${warning.code} (observed ${warning.observed_at})`);
  } catch {
    lines.push("Manabi   no local connection report yet");
  }
  if (cfg.access_token) {
    try {
      const w = await whoami();
      lines.push(`Folders  ${w.root_folders.length}`);
    } catch {
      lines.push(`Auth     check failed — run kioku login`);
    }
  }
  console.log(
    panel({
      title: "Kioku status",
      body: lines.join("\n"),
      tone: cfg.access_token ? "default" : "warn",
    })
  );

  if (!cfg.access_token) {
    return;
  }

  const repoRoot = resolve(process.cwd());
  const mcpPath = join(repoRoot, ".mcp.json");
  // kioku's hooks live in the per-user settings.local.json (not the committed
  // settings.json).
  const hookPath = join(repoRoot, ".claude", "settings.local.json");
  const claudeMdPath = join(repoRoot, "CLAUDE.md");
  const git = detectGit(repoRoot);

  section("This repo");
  info(
    git.isRepo
      ? `git: ${git.owner ? `${git.owner}/${git.repo}` : "(no remote)"}`
      : "git: not a repo"
  );
  if (existsSync(mcpPath)) ok(".mcp.json wired");
  else bad(".mcp.json missing", "Run: kioku init");
  if (existsSync(hookPath)) {
    try {
      const s = JSON.parse(readFileSync(hookPath, "utf8")) as {
        hooks?: {
          SessionStart?: Array<{ hooks?: Array<{ command?: string }> }>;
        };
      };
      const has = s.hooks?.SessionStart?.some((g) =>
        g.hooks?.some((h) => (h.command ?? "").includes("kioku"))
      );
      if (has) ok("SessionStart hook installed");
      else warn("SessionStart hook not set", "Run: kioku init");
    } catch {
      warn(".claude/settings.local.json unreadable");
    }
  } else {
    warn("SessionStart hook not set", "Run: kioku init");
  }
  if (existsSync(claudeMdPath)) ok("CLAUDE.md present");
  else warn("CLAUDE.md missing");

  console.log();
}
