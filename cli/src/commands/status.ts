import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import kleur from "kleur";
import { readConfig } from "../lib/config.js";
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
  if (cfg.access_token) {
    try {
      const w = await whoami();
      lines.push(`Folders  ${w.root_folders.length}`);
    } catch (err) {
      lines.push(`Auth     check failed — run kioku login`);
    }
  }
  console.log(panel({ title: "Kioku status", body: lines.join("\n"), tone: cfg.access_token ? "default" : "warn" }));

  if (!cfg.access_token) {
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
  else bad(".mcp.json missing", "Run: kioku init");
  if (existsSync(hookPath)) {
    try {
      const s = JSON.parse(readFileSync(hookPath, "utf8")) as {
        hooks?: { SessionStart?: Array<{ command: string }> };
      };
      const has = s.hooks?.SessionStart?.some((h) =>
        h.command.includes("kioku"),
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

  // Capture state — subtle recency indicator showing the hook loop is
  // actually running.
  const statePath = join(repoRoot, ".claude", "kioku-state.json");
  if (existsSync(statePath)) {
    try {
      const state = JSON.parse(readFileSync(statePath, "utf8")) as {
        last_capture_at?: string;
        last_capture_transcript_length?: number;
      };
      if (state.last_capture_at) {
        const when = new Date(state.last_capture_at);
        const ago = relative(when);
        info(
          `last capture: ${ago}${
            state.last_capture_transcript_length
              ? kleur.dim(` (${state.last_capture_transcript_length} turns)`)
              : ""
          }`,
        );
      } else {
        info("last capture: none yet — captures fire from Claude Code's Stop hook");
      }
    } catch {
      // ignore
    }
  }
  console.log();
}

function relative(d: Date): string {
  const s = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
