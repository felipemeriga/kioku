// cli/src/ui/theme.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { isInteractive, isQuiet, sym } from "./theme.js";

test("isQuiet reflects KIOKU_QUIET", () => {
  delete process.env.KIOKU_QUIET;
  assert.equal(isQuiet(), false);
  process.env.KIOKU_QUIET = "1";
  assert.equal(isQuiet(), true);
  delete process.env.KIOKU_QUIET;
});

test("isInteractive is false when not a TTY", () => {
  // In `node --test` stdout is not a TTY.
  assert.equal(isInteractive(), false);
});

test("sym uses ASCII fallback when KIOKU_ASCII set", () => {
  process.env.KIOKU_ASCII = "1";
  assert.equal(sym.ok, "[ok]");
  delete process.env.KIOKU_ASCII;
});
