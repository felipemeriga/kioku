import { test } from "node:test";
import assert from "node:assert/strict";
import { generateInstruction } from "./session-start.js";

test("init-generated briefing remains available for Mihari maintenance", () => {
  const instruction = generateInstruction(
    ["overview", "architecture"],
    "repo-id",
  );
  assert.match(
    instruction,
    /replace_folder_briefing\(sections=<json>, pin_all=False, folder="repo-id"\)/,
  );
});
