import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parse as parseToml } from "smol-toml";
import {
  installCodexSessionStartHook,
  installCodexStopHook,
  readCodexMcpEntry,
  toStreamableHttpUrl,
  writeCodexMcpConfig,
} from "./codex.js";

/** Point CODEX_HOME at a throwaway dir so we never touch the real config.
 *  Returns the config.toml path + a cleanup fn. */
function setup(): { path: string; cleanup: () => void } {
  const home = mkdtempSync(join(tmpdir(), "kioku-codex-"));
  const prev = process.env.CODEX_HOME;
  process.env.CODEX_HOME = home;
  return {
    path: join(home, "config.toml"),
    cleanup: () => {
      if (prev === undefined) delete process.env.CODEX_HOME;
      else process.env.CODEX_HOME = prev;
      rmSync(home, { recursive: true, force: true });
    },
  };
}

const ENTRY = {
  url: "http://localhost:8001/sse",
  headers: { Authorization: "Bearer testkey123" },
};

test("toStreamableHttpUrl rewrites /sse → /mcp, leaves others alone", () => {
  assert.equal(
    toStreamableHttpUrl("http://localhost:8001/sse"),
    "http://localhost:8001/mcp"
  );
  assert.equal(
    toStreamableHttpUrl("https://x.mcp.example.com/sse"),
    "https://x.mcp.example.com/mcp"
  );
  // Already streamable-http — untouched.
  assert.equal(
    toStreamableHttpUrl("http://localhost:8001/mcp"),
    "http://localhost:8001/mcp"
  );
});

test("writeCodexMcpConfig writes a streamable-http entry with auth header", () => {
  const { path, cleanup } = setup();
  try {
    writeCodexMcpConfig(ENTRY);
    const cfg = parseToml(readFileSync(path, "utf8")) as any;
    assert.equal(cfg.mcp_servers.kioku.url, "http://localhost:8001/mcp");
    assert.equal(
      cfg.mcp_servers.kioku.http_headers.Authorization,
      "Bearer testkey123"
    );
  } finally {
    cleanup();
  }
});

test("readCodexMcpEntry round-trips key + url", () => {
  const { cleanup } = setup();
  try {
    writeCodexMcpConfig(ENTRY);
    const read = readCodexMcpEntry();
    assert.ok(read);
    assert.equal(read!.key, "testkey123");
    assert.equal(read!.entry.url, "http://localhost:8001/mcp");
  } finally {
    cleanup();
  }
});

test("hooks write the correct [[hooks.Event]] / [[hooks.Event.hooks]] nesting", () => {
  const { path, cleanup } = setup();
  try {
    const start = installCodexSessionStartHook();
    const stop = installCodexStopHook();
    assert.ok(start.addedHook);
    assert.ok(stop.addedHook);
    const cfg = parseToml(readFileSync(path, "utf8")) as any;

    const ssGroups = cfg.hooks.SessionStart;
    assert.ok(Array.isArray(ssGroups) && ssGroups.length === 1);
    const ssHandler = ssGroups[0].hooks[0];
    assert.equal(ssHandler.type, "command");
    assert.ok(ssHandler.command.endsWith(" session-start"));
    assert.ok(ssHandler.command.includes(process.execPath));
    // Absolute invocation, not a bare `kioku`.
    assert.notEqual(ssHandler.command, "kioku session-start");

    const stopHandler = cfg.hooks.Stop[0].hooks[0];
    assert.equal(stopHandler.type, "command");
    assert.ok(stopHandler.command.endsWith(" capture"));
  } finally {
    cleanup();
  }
});

test("re-installing hooks is idempotent (no duplicates)", () => {
  const { path, cleanup } = setup();
  try {
    installCodexSessionStartHook();
    const second = installCodexSessionStartHook();
    assert.equal(second.addedHook, false);
    const cfg = parseToml(readFileSync(path, "utf8")) as any;
    assert.equal(cfg.hooks.SessionStart.length, 1);
    assert.equal(cfg.hooks.SessionStart[0].hooks.length, 1);
  } finally {
    cleanup();
  }
});

test("a stale bare hook is migrated, not duplicated", () => {
  const { path, cleanup } = setup();
  try {
    writeFileSync(
      path,
      [
        "[[hooks.SessionStart]]",
        "[[hooks.SessionStart.hooks]]",
        'type = "command"',
        'command = "kioku session-start"',
        "",
      ].join("\n")
    );
    installCodexSessionStartHook();
    const cfg = parseToml(readFileSync(path, "utf8")) as any;
    const commands = (cfg.hooks.SessionStart as any[]).flatMap((g) =>
      g.hooks.map((h: any) => h.command)
    );
    assert.equal(commands.length, 1);
    assert.notEqual(commands[0], "kioku session-start");
  } finally {
    cleanup();
  }
});

test("writing MCP + hooks preserves unrelated config", () => {
  const { path, cleanup } = setup();
  try {
    writeFileSync(
      path,
      [
        'model = "gpt-5"',
        "",
        "[mcp_servers.other]",
        'url = "http://x/mcp"',
        "",
      ].join("\n")
    );
    writeCodexMcpConfig(ENTRY);
    installCodexSessionStartHook();
    const cfg = parseToml(readFileSync(path, "utf8")) as any;
    assert.equal(cfg.model, "gpt-5");
    assert.equal(cfg.mcp_servers.other.url, "http://x/mcp");
    assert.equal(cfg.mcp_servers.kioku.url, "http://localhost:8001/mcp");
  } finally {
    cleanup();
  }
});
