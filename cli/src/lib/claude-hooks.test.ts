import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  installSessionStartHook,
  removeLegacyCaptureHooks,
  secondBrainSnippet,
  isRetiredCaptureCommand,
} from "./claude.js";

function setup(seed?: unknown): string {
  const repo = mkdtempSync(join(tmpdir(), "kioku-hooks-"));
  mkdirSync(join(repo, ".claude"), { recursive: true });
  if (seed !== undefined) {
    writeFileSync(
      join(repo, ".claude", "settings.local.json"),
      JSON.stringify(seed, null, 2)
    );
  }
  return repo;
}

test("hook command is absolute (node + entry), not bare 'kioku'", () => {
  const repo = setup();
  try {
    installSessionStartHook(repo);
    const s = JSON.parse(
      readFileSync(join(repo, ".claude", "settings.local.json"), "utf8")
    );
    const cmd = s.hooks.SessionStart[0].hooks[0].command as string;
    assert.notEqual(cmd, "kioku session-start");
    assert.ok(cmd.endsWith(" session-start"));
    assert.ok(cmd.includes(process.execPath));
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("re-install migrates the stale bare hook instead of duplicating", () => {
  const repo = setup({
    hooks: {
      SessionStart: [
        { hooks: [{ type: "command", command: "kioku session-start" }] },
      ],
    },
  });
  try {
    installSessionStartHook(repo);
    const s = JSON.parse(
      readFileSync(join(repo, ".claude", "settings.local.json"), "utf8")
    );
    const groups = s.hooks.SessionStart;
    const commands = groups.flatMap((g: { hooks: { command: string }[] }) =>
      g.hooks.map((h) => h.command)
    );
    // Exactly one SessionStart hook, and it's the migrated absolute form.
    assert.equal(commands.length, 1);
    assert.notEqual(commands[0], "kioku session-start");
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("retired capture hooks are removed while session and unrelated hooks survive", () => {
  const repo = setup({
    hooks: {
      Stop: [
        {
          hooks: [
            { type: "command", command: "kioku capture" },
            { type: "command", command: "other-hook" },
          ],
        },
      ],
    },
  });
  try {
    installSessionStartHook(repo);
    assert.equal(removeLegacyCaptureHooks(repo), true);
    assert.equal(removeLegacyCaptureHooks(repo), false);
    const s = JSON.parse(
      readFileSync(join(repo, ".claude", "settings.local.json"), "utf8")
    );
    assert.ok(
      s.hooks.SessionStart[0].hooks[0].command.endsWith(" session-start")
    );
    assert.equal(s.hooks.Stop[0].hooks[0].command, "other-hook");
  } finally {
    rmSync(repo, { recursive: true, force: true });
  }
});

test("agent instructions only advertise available knowledge tools", () => {
  const snippet = secondBrainSnippet();
  assert.doesNotMatch(snippet, /Mem0|save_memory|search_memory|Stop hook/);
  assert.match(snippet, /update_folder_briefing_section/);
});

test("capture migration only matches Kioku commands including installed absolute paths", () => {
  assert.equal(isRetiredCaptureCommand("kioku capture"), true);
  assert.equal(
    isRetiredCaptureCommand(
      "'/opt/homebrew/bin/node' '/opt/homebrew/lib/node_modules/@felipemeriga/kioku/dist/index.js' capture"
    ),
    true
  );
  assert.equal(isRetiredCaptureCommand("other-tool capture"), false);
  assert.equal(isRetiredCaptureCommand("kioku session-start"), false);
});
