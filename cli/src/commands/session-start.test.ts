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

test("initial briefing requires local, semantic, and graph evidence", () => {
  const instruction = generateInstruction(
    ["overview", "architecture", "preferences", "how_it_runs", "deployment"],
    "repo-id",
  );
  assert.match(instruction, /local grep\/search tool/);
  assert.match(instruction, /`code_search` semantic/);
  assert.match(instruction, /`find_references`/);
  assert.match(instruction, /\.github\/workflows\//);
  assert.match(instruction, /distinct supported run mode/);
  assert.doesNotMatch(instruction, /following the schema shapes:.*preferences/);
});
