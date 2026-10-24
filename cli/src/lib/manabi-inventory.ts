import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";

export type AgentProvider = "claude" | "codex";
export interface InventoryRepo {
  id: string;
  folder_id: string;
  name: string;
  path: string;
  agents: AgentProvider[];
  initialized_at: string;
  available: boolean;
}
interface Entry extends InventoryRepo {
  api_base: string;
  user_id: string;
}
export interface InventoryWarning {
  code: "repo_unavailable" | "registry_unreadable";
  observed_at: string;
}
export interface Identity {
  api_base: string;
  user_id?: string;
}
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function readRegistry(path: string): Entry[] {
  if (!existsSync(path)) return [];
  const value: unknown = JSON.parse(readFileSync(path, "utf8"));
  if (!Array.isArray(value) || value.length > 200)
    throw new Error(
      "Invalid Manabi repository registry; re-run kioku init after repairing inventory.json"
    );
  for (const row of value) {
    if (
      !row ||
      typeof row.path !== "string" ||
      typeof row.api_base !== "string" ||
      typeof row.user_id !== "string" ||
      typeof row.name !== "string" ||
      row.name.length > 120 ||
      row.path.length > 1024 ||
      typeof row.id !== "string" ||
      !/^[a-f0-9]{64}$/.test(row.id) ||
      typeof row.initialized_at !== "string" ||
      !Number.isFinite(Date.parse(row.initialized_at)) ||
      !uuid.test(row.folder_id) ||
      !Array.isArray(row.agents) ||
      row.agents.some((x: unknown) => x !== "claude" && x !== "codex")
    )
      throw new Error("Invalid Manabi repository registry");
  }
  // Project the transport schema; unrelated local fields must never be uploaded.
  return (value as Entry[]).map(
    ({
      id,
      folder_id,
      name,
      path,
      agents,
      initialized_at,
      api_base,
      user_id,
    }) => ({
      id,
      folder_id,
      name,
      path,
      agents,
      initialized_at,
      api_base,
      user_id,
      available: true,
    })
  );
}
export function recordInitializedRepo(
  registry: string,
  identity: Identity & { user_id: string },
  repo: {
    path: string;
    folder_id: string;
    name: string;
    agents: AgentProvider[];
  }
): void {
  if (!uuid.test(repo.folder_id))
    throw new Error("Invalid repository folder binding");
  const canonical = realpathSync(repo.path);
  const rows = readRegistry(registry);
  const id = createHash("sha256")
    .update(`${identity.api_base}\0${identity.user_id}\0${canonical}`)
    .digest("hex");
  const prior = rows.find((row) => row.id === id);
  const entry: Entry = {
    ...identity,
    ...repo,
    path: canonical,
    id,
    available: true,
    initialized_at: prior?.initialized_at ?? new Date().toISOString(),
    agents: [
      ...new Set([
        ...(prior?.folder_id === repo.folder_id ? prior.agents : []),
        ...repo.agents,
      ]),
    ].sort(),
  };
  const next = [...rows.filter((row) => row.id !== id), entry];
  if (next.length > 200)
    throw new Error(
      "Manabi supports up to 200 initialized repository paths per user registry"
    );
  mkdirSync(dirname(registry), { recursive: true, mode: 0o700 });
  const temp = `${registry}.${randomUUID()}.tmp`;
  writeFileSync(temp, JSON.stringify(next), { mode: 0o600 });
  renameSync(temp, registry);
}
function stillConfigured(path: string, agent: AgentProvider): boolean {
  const marker = agent === "claude" ? "CLAUDE.md" : "AGENTS.md";
  try {
    if (
      !readFileSync(join(path, marker), "utf8").includes(
        "BEGIN kioku second-brain"
      )
    )
      return false;
    if (agent === "claude")
      return Boolean(
        JSON.parse(readFileSync(join(path, ".mcp.json"), "utf8")).mcpServers
          ?.kioku
      );
    return true;
  } catch (error) {
    // A removed binding is unconfigured; temporarily unreadable files retain last-known state.
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    return true;
  }
}
export function readInventory(
  registry: string,
  identity: Identity
): { repositories: InventoryRepo[]; warnings: InventoryWarning[] } {
  try {
    const repositories: InventoryRepo[] = [];
    for (const { api_base, user_id, ...row } of readRegistry(registry)) {
      if (api_base !== identity.api_base || user_id !== identity.user_id)
        continue;
      const available = existsSync(row.path);
      const agents = available
        ? row.agents.filter((agent) => stillConfigured(row.path, agent))
        : row.agents;
      if (agents.length) repositories.push({ ...row, agents, available });
    }
    return {
      repositories,
      warnings: repositories.some((row) => !row.available)
        ? [{ code: "repo_unavailable", observed_at: new Date().toISOString() }]
        : [],
    };
  } catch {
    return {
      repositories: [],
      warnings: [
        { code: "registry_unreadable", observed_at: new Date().toISOString() },
      ],
    };
  }
}

export function inventoryPath(configPath: string): string {
  return join(dirname(configPath), "inventory.json");
}
