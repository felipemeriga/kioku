import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { readCodeSource, uploadCodeChunks } from "./code-chunks.js";

test("source reads reject links, traversal and oversized files", () => {
  const temp = mkdtempSync(join(tmpdir(), "kioku-source-security-"));
  try {
    const repo = join(temp, "repo");
    mkdirSync(repo);
    writeFileSync(join(temp, "private.ts"), "private sentinel");
    writeFileSync(join(repo, "normal.ts"), "export const safe = true;");
    symlinkSync(join(temp, "private.ts"), join(repo, "linked.ts"));
    symlinkSync(temp, join(repo, "linked-dir"), "dir");
    writeFileSync(join(repo, "large.ts"), "a".repeat(300_001));
    assert.equal(
      readCodeSource(repo, "normal.ts"),
      "export const safe = true;",
    );
    for (const file of [
      "linked.ts",
      "linked-dir/private.ts",
      "../private.ts",
      join(temp, "private.ts"),
      "large.ts",
    ]) {
      assert.equal(readCodeSource(repo, file), null, file);
    }
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
});

test("code upload never sends external symlink content", async () => {
  const temp = mkdtempSync(join(tmpdir(), "kioku-upload-security-"));
  const previous = globalThis.fetch;
  const payloads: string[] = [];
  try {
    const repo = join(temp, "repo");
    mkdirSync(repo);
    writeFileSync(join(temp, "private.ts"), "private sentinel");
    writeFileSync(join(repo, "normal.ts"), "export const safe = true;");
    symlinkSync(join(temp, "private.ts"), join(repo, "linked.ts"));
    globalThis.fetch = async (_url, init) => {
      if (init?.method === "POST") payloads.push(String(init.body));
      return new Response(
        JSON.stringify(
          init?.method === "POST" ? { chunks_queued: 1 } : { files: {} },
        ),
      );
    };
    await uploadCodeChunks({
      repoRoot: repo,
      base: "https://example.invalid",
      apiKey: "test-only",
      folderId: "folder",
      folderName: "repo",
      files: ["normal.ts", "linked.ts", "../private.ts"],
      deletedFiles: [],
      nodes: [],
      norm: (p) => p ?? "",
      log: { info() {}, warn() {} },
    });
    assert.equal(payloads.length, 1);
    assert.match(payloads[0], /export const safe/);
    assert.doesNotMatch(payloads[0], /private sentinel|linked\.ts/);
  } finally {
    globalThis.fetch = previous;
    rmSync(temp, { recursive: true, force: true });
  }
});
