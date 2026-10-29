import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as sleep } from "node:timers/promises";
import { spawn } from "node:child_process";
import { getRootKey, saveRootKey, withInitConfigLock } from "./root-keys.js";

test("three concurrent inits mint once and keep a valid shared root key", async () => {
  const dir = mkdtempSync(join(tmpdir(), "kioku-init-lock-"));
  const prior = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  let minted = 0;
  let active = 0;
  let peak = 0;
  try {
    const keys = await Promise.all(
      Array.from({ length: 3 }, () =>
        withInitConfigLock(async () => {
          peak = Math.max(peak, ++active);
          try {
            const stored = getRootKey("shared-root");
            if (stored) return stored.key;
            await sleep(25);
            const key = `key-${++minted}`;
            saveRootKey("shared-root", {
              key,
              url: "https://example.com/mcp",
              headers: { Authorization: `Bearer ${key}` },
            });
            return key;
          } finally {
            active--;
          }
        }),
      ),
    );
    assert.equal(peak, 1);
    assert.equal(minted, 1);
    assert.deepEqual(keys, ["key-1", "key-1", "key-1"]);
    assert.equal(getRootKey("shared-root")?.key, "key-1");
  } finally {
    if (prior === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = prior;
    rmSync(dir, { recursive: true, force: true });
  }
});

test("separate CLI processes share one root key during concurrent init", async () => {
  const dir = mkdtempSync(join(tmpdir(), "kioku-init-processes-"));
  const moduleUrl = new URL("./root-keys.js", import.meta.url).href;
  const script = `
    import { getRootKey, saveRootKey, withInitConfigLock } from ${JSON.stringify(moduleUrl)};
    await withInitConfigLock(async () => {
      let stored = getRootKey('shared-root');
      if (!stored) {
        await new Promise(resolve => setTimeout(resolve, 50));
        stored = { key: 'key-' + process.pid, url: 'https://example.com/mcp', headers: {} };
        saveRootKey('shared-root', stored);
      }
      process.stdout.write(stored.key);
    });
  `;
  const child = () =>
    new Promise<string>((resolve, reject) => {
      const processChild = spawn(
        process.execPath,
        ["--input-type=module", "-e", script],
        {
          env: { ...process.env, XDG_CONFIG_HOME: dir },
        },
      );
      let output = "";
      let error = "";
      processChild.stdout.on("data", (data) => {
        output += data;
      });
      processChild.stderr.on("data", (data) => {
        error += data;
      });
      processChild.on("exit", (code) =>
        code === 0 ? resolve(output) : reject(new Error(error)),
      );
    });
  try {
    const keys = await Promise.all([child(), child(), child()]);
    assert.equal(new Set(keys).size, 1);
    assert.ok(keys[0].startsWith("key-"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
