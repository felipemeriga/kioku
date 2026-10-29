import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, realpathSync, statSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import type { InventoryRepo } from "./manabi-inventory.js";
import type { MemoryEvent } from "./manabi-memory-source.js";

export interface AgentMemoryFile {
  file: string;
  folderId: string;
  source: "claude_memory" | "codex_memory";
}

const hash = (value: string) => createHash("sha256").update(value).digest("hex");
const projectDirectory = (home: string, path: string) =>
  join(home, ".claude", "projects", path.replace(/[^A-Za-z0-9-]/g, "-"), "memory");

/** Discover only files belonging to an initialized repository. Codex's global
 * registry is used as a pointer map; it is never uploaded as one document. */
export function discoverAgentMemoryFiles(home: string, repositories: InventoryRepo[]): AgentMemoryFile[] {
  const found: AgentMemoryFile[] = [];
  const codexHome = process.env.CODEX_HOME || join(home, ".codex");
  const memoryRoot = join(codexHome, "memories");
  let registry = "";
  try { registry = readFileSync(join(memoryRoot, "MEMORY.md"), "utf8"); }
  catch { /* Codex native memory may be disabled. */ }
  for (const repo of repositories) {
    if (!repo.available) continue;
    let canonical: string;
    try { canonical = realpathSync(repo.path); } catch { continue; }
    if (repo.agents.includes("claude")) {
      for (const dir of new Set([projectDirectory(home, repo.path), projectDirectory(home, canonical)])) {
        try {
          for (const name of readdirSync(dir)) {
            if (!name.endsWith(".md") || name === "MEMORY.md") continue;
            const file = join(dir, name);
            if (realpathSync(file).startsWith(realpathSync(dir) + sep))
              found.push({ file, folderId: repo.folder_id, source: "claude_memory" });
          }
        } catch { /* A project may have no native memories yet. */ }
      }
    }
    if (repo.agents.includes("codex")) {
      for (const line of registry.split("\n")) {
        const match = line.match(/^- (rollout_summaries\/[^ ()]+\.md) \(cwd=([^,]+),/);
        if (!match) continue;
        let cwd: string;
        try { cwd = realpathSync(match[2]); } catch { continue; }
        if (cwd !== canonical && !cwd.startsWith(canonical + sep)) continue;
        const file = resolve(memoryRoot, match[1]);
        if (file.startsWith(resolve(memoryRoot, "rollout_summaries") + sep) && existsSync(file))
          found.push({ file, folderId: repo.folder_id, source: "codex_memory" });
      }
    }
  }
  return [...new Map(found.map((item) => [`${item.source}:${item.folderId}:${item.file}`, item])).values()];
}

export function readAgentMemoryFile(item: AgentMemoryFile): MemoryEvent {
  if (statSync(item.file).size > 60_000) throw new Error("Agent memory file exceeds capture limit");
  const content = readFileSync(item.file, "utf8");
  const contentHash = hash(content);
  const sessionId = hash(item.file).slice(0, 64);
  return {
    type: "memory_post", protocol: 1,
    event_id: hash(`${item.source}\0${item.folderId}\0${sessionId}\0${contentHash}`),
    content_hash: contentHash, folder_id: item.folderId, session_id: sessionId,
    source: item.source, source_schema_version: 1, record_position: 0,
    event_time: null, observed_at: new Date().toISOString(),
    provenance: "agent_memory", sensitivity: "normal", content,
  };
}
