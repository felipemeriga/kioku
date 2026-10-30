import { test } from "node:test";
import assert from "node:assert/strict";
import { parseSummarizerOutput, previousSessionContext } from "./memory.js";
import { journalHeader, renderEntry } from "../lib/agent-journal.js";

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

test("legacy session entries provide context until an overview is captured", () => {
  const turn = { agent: "codex" as const, sessionId: "session-1", turnId: "first", user: "", assistant: "" };
  const first = journalHeader("2026-10-29") + renderEntry(
    turn, "- User wants reliable uploads.\n- Investigated slow requests.", Date.parse("2026-10-29T12:00:00Z"),
  );
  const other = journalHeader("2026-10-29") + renderEntry(
    { ...turn, sessionId: "another-session" }, "- Unrelated work.\n- Done.", Date.parse("2026-10-29T12:01:00Z"),
  );
  const legacy = previousSessionContext([first, other], "codex", "session-1");
  assert.match(legacy.earlierEntries ?? "", /reliable uploads/);
  assert.doesNotMatch(legacy.earlierEntries ?? "", /Unrelated work/);

  const second = journalHeader("2026-10-30") + renderEntry(
    { ...turn, turnId: "second" }, "- Found the bottleneck.\n- Fixed it.", Date.parse("2026-10-30T12:00:00Z"),
    { title: "Improve upload reliability", summary: "The user wants reliable uploads. We found and fixed the bottleneck." },
  );
  const updated = previousSessionContext([first, second], "codex", "session-1");
  assert.equal(updated.title, "Improve upload reliability");
  assert.match(updated.summary ?? "", /found and fixed/);
  assert.equal(updated.earlierEntries, undefined);
});
