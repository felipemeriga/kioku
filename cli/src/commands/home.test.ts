// cli/src/commands/home.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { HOME_ACTIONS } from "./home.js";

test("every non-quit action maps to a runnable handler", () => {
  for (const a of ["ls", "search", "briefing", "init", "status", "doctor", "login", "logout"] as const) {
    assert.equal(typeof HOME_ACTIONS[a], "function", `missing handler for ${a}`);
  }
});
