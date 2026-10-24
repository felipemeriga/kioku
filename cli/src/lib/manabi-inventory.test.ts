import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  rmSync,
  symlinkSync,
  realpathSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { recordInitializedRepo, readInventory } from "./manabi-inventory.js";
import { machineInfo } from "./manabi-machine.js";
import { knownProjectPaths, configuredAgents } from "./manabi-discovery.js";

test("inventory keeps both providers, canonicalizes aliases and isolates accounts", () => {
  const root = mkdtempSync(join(tmpdir(), "manabi-repos-"));
  try {
    const path = join(root, "repo");
    mkdirSync(path);
    symlinkSync(path, join(root, "alias"));
    writeFileSync(join(path, "CLAUDE.md"), "<!-- BEGIN kioku second-brain -->");
    writeFileSync(join(path, "AGENTS.md"), "<!-- BEGIN kioku second-brain -->");
    writeFileSync(
      join(path, ".mcp.json"),
      JSON.stringify({ mcpServers: { kioku: {} } })
    );
    const registry = join(root, "registry.json");
    const identity = { api_base: "https://kioku.example", user_id: "alice" };
    const repo = {
      path,
      folder_id: randomUUID(),
      name: "repo",
      agents: ["claude" as const],
    };
    recordInitializedRepo(registry, identity, repo);
    recordInitializedRepo(registry, identity, {
      ...repo,
      path: join(root, "alias"),
      agents: ["codex"],
    });
    const snapshot = readInventory(registry, identity);
    assert.equal(snapshot.repositories.length, 1);
    assert.deepEqual(snapshot.repositories[0].agents, ["claude", "codex"]);
    assert.equal(snapshot.repositories[0].path, realpathSync(path));
    assert.equal(
      readInventory(registry, { ...identity, user_id: "bob" }).repositories
        .length,
      0
    );
    assert.equal(
      readInventory(registry, {
        ...identity,
        api_base: "https://other.example",
      }).repositories.length,
      0
    );
    rmSync(join(path, "AGENTS.md"));
    assert.deepEqual(readInventory(registry, identity).repositories[0].agents, [
      "claude",
    ]);
    rmSync(path, { recursive: true });
    assert.equal(
      readInventory(registry, identity).warnings[0].code,
      "repo_unavailable"
    );
    writeFileSync(registry, "{broken");
    assert.equal(
      readInventory(registry, identity).warnings[0].code,
      "registry_unreadable"
    );
    assert.throws(() => recordInitializedRepo(registry, identity, repo));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("friendly OS names reject IP hostname fallback and identify only observed distros", () => {
  assert.deepEqual(
    machineInfo({
      platform: "darwin",
      hostname: "192.168.0.164",
      architecture: "arm64",
      run: () => "Felipe’s MacBook",
    }),
    {
      name: "Felipe’s MacBook",
      os_name: "macOS",
      os_id: "macos",
      architecture: "arm64",
    }
  );
  assert.equal(
    machineInfo({
      platform: "darwin",
      hostname: "192.168.0.164",
      run: () => "",
    }).name,
    "macOS computer"
  );
  assert.equal(
    machineInfo({
      platform: "linux",
      hostname: "box",
      run: () => "",
      osRelease: "ID=ubuntu\n",
    }).os_name,
    "Ubuntu"
  );
  assert.equal(
    machineInfo({
      platform: "linux",
      hostname: "box",
      run: () => "",
      osRelease: "ID=debian\n",
    }).os_name,
    "Linux"
  );
});

test("discovery uses provider path indexes and requires explicit Kioku project markers", () => {
  const home = mkdtempSync(join(tmpdir(), "manabi-discover-"));
  try {
    const repo = join(home, "repo");
    mkdirSync(repo);
    mkdirSync(join(home, ".codex"));
    writeFileSync(
      join(home, ".claude.json"),
      JSON.stringify({ projects: { [repo]: {}, "/unknown": {} } })
    );
    writeFileSync(
      join(home, ".codex", "config.toml"),
      '[projects."/codex-project"]\ntrust_level="trusted"'
    );
    assert.deepEqual(knownProjectPaths(home), [
      repo,
      "/unknown",
      "/codex-project",
    ]);
    writeFileSync(join(repo, "CLAUDE.md"), "unrelated");
    writeFileSync(join(repo, "AGENTS.md"), "unrelated");
    assert.deepEqual(configuredAgents(repo), []);
    writeFileSync(
      join(repo, ".mcp.json"),
      JSON.stringify({ mcpServers: { kioku: { url: "https://example" } } })
    );
    writeFileSync(join(repo, "CLAUDE.md"), "<!-- BEGIN kioku second-brain -->");
    writeFileSync(join(repo, "AGENTS.md"), "<!-- BEGIN kioku second-brain -->");
    assert.deepEqual(configuredAgents(repo), ["claude", "codex"]);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});
