import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import kleur from "kleur";
import { readConfig } from "../lib/config.js";
import { whoami } from "../lib/api.js";
import { detectGit } from "../lib/git.js";
import { bad, info, ok, section, warn } from "../lib/banner.js";

export async function status(): Promise<void> {
  const cfg = readConfig();
  section("Status");
  info(`API base: ${cfg.api_base}`);

  if (!cfg.access_token) {
    warn("Not signed in.", "Run: agentic-rag login");
    return;
  }
  try {
    const w = await whoami();
    ok(`Signed in as ${cfg.email}`, `${w.root_folders.length} root folder${w.root_folders.length === 1 ? "" : "s"}`);
  } catch (err) {
    warn(
      `Auth check failed: ${err instanceof Error ? err.message : err}`,
      "Try: agentic-rag login",
    );
    return;
  }

  const repoRoot = resolve(process.cwd());
  const mcpPath = join(repoRoot, ".mcp.json");
  const hookPath = join(repoRoot, ".claude", "settings.json");
  const claudeMdPath = join(repoRoot, "CLAUDE.md");
  const git = detectGit(repoRoot);

  section("This repo");
  info(
    git.isRepo
      ? `git: ${git.owner ? `${git.owner}/${git.repo}` : "(no remote)"}`
      : "git: not a repo",
  );
  if (existsSync(mcpPath)) ok(".mcp.json wired");
  else bad(".mcp.json missing", "Run: agentic-rag init");
  if (existsSync(hookPath)) {
    try {
      const s = JSON.parse(readFileSync(hookPath, "utf8")) as {
        hooks?: { SessionStart?: Array<{ command: string }> };
      };
      const has = s.hooks?.SessionStart?.some((h) =>
        h.command.includes("agentic-rag"),
      );
      if (has) ok("SessionStart hook installed");
      else warn("SessionStart hook not set");
    } catch {
      warn(".claude/settings.json unreadable");
    }
  } else {
    warn(".claude/settings.json missing");
  }
  if (existsSync(claudeMdPath)) ok("CLAUDE.md present");
  else warn("CLAUDE.md missing");
  console.log();
}
