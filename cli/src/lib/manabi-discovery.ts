import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import { parse } from "smol-toml";
import type { AgentProvider } from "./manabi-inventory.js";
export function knownProjectPaths(home = homedir()): string[] {
  const paths = new Set<string>();
  try {
    const cfg = JSON.parse(readFileSync(join(home, ".claude.json"), "utf8"));
    for (const path of Object.keys(cfg.projects ?? {}).slice(0, 200))
      paths.add(path);
  } catch {
    /* Optional provider index; never crawl the disk. */
  }
  try {
    const cfg = parse(
      readFileSync(join(home, ".codex", "config.toml"), "utf8")
    );
    for (const path of Object.keys(cfg.projects ?? {}).slice(0, 200))
      paths.add(path);
  } catch {
    /* Optional provider index. */
  }
  return [...paths].slice(0, 200);
}
export function configuredAgents(path: string): AgentProvider[] {
  const agents: AgentProvider[] = [];
  try {
    const cfg = JSON.parse(readFileSync(join(path, ".mcp.json"), "utf8"));
    if (
      cfg.mcpServers?.kioku &&
      readFileSync(join(path, "CLAUDE.md"), "utf8").includes(
        "BEGIN kioku second-brain"
      )
    )
      agents.push("claude");
  } catch {
    /* No explicit Claude binding. */
  }
  if (existsSync(join(path, "AGENTS.md"))) {
    try {
      if (
        readFileSync(join(path, "AGENTS.md"), "utf8").includes(
          "BEGIN kioku second-brain"
        )
      )
        agents.push("codex");
    } catch {
      /* Unreadable project instructions. */
    }
  }
  return agents;
}
