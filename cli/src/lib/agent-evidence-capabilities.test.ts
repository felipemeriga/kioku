import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  evidenceHookCapabilities,
  EVIDENCE_HOOK_EVENTS,
} from "./agent-evidence-capabilities.js";
import { installCodexEvidenceHooks } from "./codex.js";
import { installClaudeEvidenceHooks } from "./claude.js";
test("capability status separates audited schemas, hook installation and host trust", () => {
  const root = mkdtempSync(join(tmpdir(), "kioku-capabilities-")),
    oldCodex = process.env.CODEX_HOME,
    oldClaude = process.env.CLAUDE_CONFIG_DIR;
  process.env.CODEX_HOME = join(root, "codex");
  process.env.CLAUDE_CONFIG_DIR = join(root, "claude");
  try {
    installCodexEvidenceHooks();
    installClaudeEvidenceHooks(root);
    const status = evidenceHookCapabilities(root, {
      codex: "0.165.0",
      claude_code: "2.1.285",
    }) as Record<string, any>;
    assert.equal(status.codex.schema_status, "verified");
    assert.equal(status.codex.capture_status, "configured");
    assert.deepEqual(
      status.claude_code.configured_events,
      EVIDENCE_HOOK_EVENTS,
    );
    assert.equal(status.claude_code.runtime_execution_verified, false);
    const unknown = evidenceHookCapabilities(root, {
      codex: "0.1.0",
      claude_code: null,
    }) as Record<string, any>;
    assert.equal(unknown.codex.reason, "version_not_audited");
    assert.equal(unknown.claude_code.reason, "cli_unavailable");
    mkdirSync(process.env.CLAUDE_CONFIG_DIR, { recursive: true });
    writeFileSync(
      join(process.env.CLAUDE_CONFIG_DIR, "settings.json"),
      JSON.stringify({ disableAllHooks: true }),
    );
    const disabled = evidenceHookCapabilities(root, {
      codex: "0.165.0",
      claude_code: "2.1.285",
    }) as Record<string, any>;
    assert.equal(disabled.claude_code.reason, "hooks_disabled");
  } finally {
    if (oldCodex === undefined) delete process.env.CODEX_HOME;
    else process.env.CODEX_HOME = oldCodex;
    if (oldClaude === undefined) delete process.env.CLAUDE_CONFIG_DIR;
    else process.env.CLAUDE_CONFIG_DIR = oldClaude;
    rmSync(root, { recursive: true, force: true });
  }
});
