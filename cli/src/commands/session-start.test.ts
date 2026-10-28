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

test("initial briefing uses available code search and checks uncertainty", () => {
  const instruction = generateInstruction(
    ["overview", "architecture", "preferences", "how_it_runs", "deployment"],
    "repo-id",
  );
  assert.match(instruction, /normal local search\/grep tool/);
  assert.match(instruction, /`code_search` \(semantic search\)/);
  assert.match(instruction, /`find_references`/);
  assert.match(instruction, /you do not need to call every tool/);
  assert.match(instruction, /compare it with/);
  assert.match(instruction, /Never invent a fact/);
  assert.match(instruction, /Omit unsupported/);
  assert.match(instruction, /\.github\/workflows\//);
  assert.match(instruction, /distinct supported run mode/);
  assert.doesNotMatch(instruction, /following the schema shapes:.*preferences/);
});
