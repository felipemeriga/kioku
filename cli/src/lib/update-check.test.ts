import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { startUpdateChecks } from "./update-check.js";

test("home update checks start only for interactive terminals and reuse cache", async () => {
  const originalFetch = globalThis.fetch;
  const originalTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
  const originalCache = process.env.XDG_CACHE_HOME;
  const originalDisabled = process.env.KIOKU_NO_UPDATE_CHECK;
  const cache = mkdtempSync(join(tmpdir(), "kioku-update-check-"));
  let calls = 0;
  let stop = () => {};
  try {
    delete process.env.KIOKU_NO_UPDATE_CHECK;
    process.env.XDG_CACHE_HOME = cache;
    globalThis.fetch = async () => {
      calls++;
      return new Response(JSON.stringify({ version: "1.0.0" }));
    };
    Object.defineProperty(process.stdout, "isTTY", { value: false, configurable: true });
    startUpdateChecks("1.0.0")();
    assert.equal(calls, 0);
    Object.defineProperty(process.stdout, "isTTY", { value: true, configurable: true });
    stop = startUpdateChecks("1.0.0");
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(calls, 1);
    stop();
    stop = startUpdateChecks("1.0.0");
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(calls, 1);
  } finally {
    stop();
    globalThis.fetch = originalFetch;
    if (originalTTY) Object.defineProperty(process.stdout, "isTTY", originalTTY);
    else Reflect.deleteProperty(process.stdout, "isTTY");
    if (originalCache === undefined) delete process.env.XDG_CACHE_HOME;
    else process.env.XDG_CACHE_HOME = originalCache;
    if (originalDisabled === undefined) delete process.env.KIOKU_NO_UPDATE_CHECK;
    else process.env.KIOKU_NO_UPDATE_CHECK = originalDisabled;
    rmSync(cache, { recursive: true, force: true });
  }
});
