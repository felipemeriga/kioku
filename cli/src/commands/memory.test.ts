import { test } from "node:test";
import assert from "node:assert/strict";
import { parseSummarizerOutput } from "./memory.js";

test("session journal output keeps cumulative context and turn bullets", () => {
  const result = parseSummarizerOutput(
    JSON.stringify({
      title: "Investigate retry handling",
      summary: "Checked retry paths, then fixed `NotFound` recovery.",
      bullets: [
        "- Confirmed the retry failure.",
        "- Fixed `retryRequest()` in `src/retry.ts`.",
      ],
    }),
  );
  assert.equal(result.title, "Investigate retry handling");
  assert.match(result.summary, /fixed/);
  assert.match(result.bullets, /src\/retry\.ts/);
});

test("session overview retains more than the former 800-character limit", () => {
  const summary =
    "The user wants a durable introduction to the session. ".repeat(22);
  const result = parseSummarizerOutput(
    JSON.stringify({
      title: "Improve session memory",
      summary,
      bullets: ["- Identified the goal.", "- Updated the session overview."],
    }),
  );
  assert.equal(result.summary, summary.trim());
  assert.ok(result.summary.length > 800);
});
