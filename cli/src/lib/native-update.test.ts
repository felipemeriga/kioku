import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { installNativeUpdate } from "./native-update.js";

test("native update rejects an installer with a mismatched checksum", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input) =>
    new Response(
      String(input).endsWith("SHA256SUMS")
        ? `${"0".repeat(64)}  ${process.platform === "win32" ? "install.ps1" : "install.sh"}\n`
        : "exit 1\n",
      { status: 200 }
    );
  try {
    await assert.rejects(
      installNativeUpdate("1.2.3"),
      /checksum verification failed/
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("native update rejects release path injection", async () => {
  await assert.rejects(
    installNativeUpdate("1.2.3/../../bad"),
    /Invalid CLI release version/
  );
});

test("verified Unix updater runs the release installer", async (context) => {
  if (process.platform === "win32") return context.skip("Unix shell installer");
  const root = mkdtempSync(join(tmpdir(), "kioku-updater-test-"));
  const marker = join(root, "ran");
  const script = `#!/bin/sh\nprintf '%s' "$KIOKU_VERSION" > "$KIOKU_TEST_MARKER"\n`;
  const hash = createHash("sha256").update(script).digest("hex");
  const originalFetch = globalThis.fetch;
  const originalMarker = process.env.KIOKU_TEST_MARKER;
  process.env.KIOKU_TEST_MARKER = marker;
  globalThis.fetch = async (input) =>
    new Response(
      String(input).endsWith("SHA256SUMS") ? `${hash}  install.sh\n` : script
    );
  try {
    await installNativeUpdate("1.2.3");
    assert.equal(readFileSync(marker, "utf8"), "1.2.3");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalMarker === undefined) delete process.env.KIOKU_TEST_MARKER;
    else process.env.KIOKU_TEST_MARKER = originalMarker;
    rmSync(root, { recursive: true, force: true });
  }
});
