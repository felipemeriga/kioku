import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { journalHeader, localDateTime, mergeJournals, parseJournal, parseTurn, renderEntry, withJournalLock, writeJournalAtomic } from "./agent-journal.js";
import { installClaudeMemoryCaptureHook } from "./claude.js";

const day = "2026-10-29";
const timestamp = Date.parse("2026-10-29T10:00:00-03:00");

test("Claude and Codex native transcript shapes produce identifiable turns", () => {
  const dir = mkdtempSync(join(tmpdir(), "kioku-journal-parser-"));
  try {
    const claude = join(dir, "claude.jsonl");
    writeFileSync(claude, [
      { type: "user", uuid: "u1", sessionId: "c1", message: { content: "Read the file" } },
      { type: "assistant", sessionId: "c1", message: { content: [{ type: "tool_use", name: "Read" }] } },
      { type: "assistant", sessionId: "c1", message: { content: [{ type: "text", text: "Updated the file." }] } },
    ].map((value) => JSON.stringify(value)).join("\n"));
    const codex = join(dir, "codex.jsonl");
    writeFileSync(codex, [
      { type: "event_msg", payload: { type: "item_completed", item: { type: "UserMessage", id: "u2", content: [{ type: "text", text: "Fix the query" }] } } },
      { type: "response_item", payload: { type: "message", role: "assistant", content: [{ type: "output_text", text: "Fixed the query." }] } },
    ].map((value) => JSON.stringify(value)).join("\n"));
    assert.equal(parseTurn("claude_code", { session_id: "c1", transcript_path: claude })?.assistant, "Updated the file.");
    assert.equal(parseTurn("codex", { session_id: "x1", transcript_path: codex })?.user, "Fix the query");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("daily merge keeps both agents and ignores replay", () => {
  const c = { agent: "claude_code" as const, sessionId: "c1", turnId: "t1", user: "a", assistant: "b" };
  const x = { agent: "codex" as const, sessionId: "x1", turnId: "t2", user: "a", assistant: "b" };
  const first = journalHeader(day) + renderEntry(c, "- Started task\n- Completed task", timestamp);
  assert.ok(parseJournal(first)[0].metadata.computer_name);
  assert.equal(parseJournal(first)[0].metadata.captured_at, timestamp);
  const second = journalHeader(day) + renderEntry(x, "- Found issue\n- Fixed issue", timestamp);
  const merged = mergeJournals(day, first, second);
  assert.equal(parseJournal(merged).length, 2);
  assert.equal(mergeJournals(day, merged, first), merged);
  const sessionEntry = renderEntry(c, "- Started task\n- Completed task", timestamp, {
    title: "Build session timeline",
    summary: "Created the timeline view.",
  });
  assert.equal(parseJournal(sessionEntry)[0].metadata.session_title, "Build session timeline");
  const olderLocal = first.replace("Started task", "Tarefa iniciada");
  assert.equal(parseJournal(mergeJournals(day, first, olderLocal))[0].block.includes("Started task"), true);
});

test("one daily session header precedes its turns and follows the latest summary", () => {
  const turn = { agent: "codex" as const, sessionId: "session-42", turnId: "one", user: "a", assistant: "b" };
  const first = renderEntry(turn, "- Started investigation\n- Checked logs", timestamp, {
    title: "Investigate retries", summary: "Checked the logs.",
  });
  const second = renderEntry({ ...turn, turnId: "two" }, "- Fixed retry\n- Tests passed", timestamp + 60_000, {
    title: "Fix retry handling", summary: "Checked the logs, fixed retry handling, and passed tests.",
  });
  const markdown = mergeJournals(day, journalHeader(day) + first, journalHeader(day) + second);
  assert.equal((markdown.match(/^## Codex session /gm) ?? []).length, 1);
  assert.match(markdown, /\*\*About:\*\* Fix retry handling/);
  assert.match(markdown, /\*\*Done so far:\*\* Checked the logs, fixed retry handling, and passed tests/);
  assert.ok(markdown.indexOf("## Codex session") < markdown.indexOf("### "));
  assert.deepEqual(parseJournal(markdown).map((entry) => entry.metadata.turn_id), ["one", "two"]);
  const olderWriterTurn = renderEntry({ ...turn, turnId: "old-cli" }, "- Follow-up\n- No summary", timestamp + 120_000);
  const withOlderWriter = mergeJournals(day, markdown, journalHeader(day) + olderWriterTurn);
  assert.match(withOlderWriter, /\*\*Done so far:\*\* Checked the logs, fixed retry handling, and passed tests/);

  const nextDay = "2026-10-30";
  const continuation = renderEntry({ ...turn, turnId: "three" }, "- Reviewed fix\n- No regression", timestamp + 86_400_000, {
    title: "Fix retry handling", summary: "Checked logs, fixed retry handling, and confirmed no regression.",
  });
  const continuationMarkdown = mergeJournals(nextDay, journalHeader(nextDay), journalHeader(nextDay) + continuation);
  assert.match(markdown, /"session_id":"session-42"/);
  assert.match(continuationMarkdown, /"session_id":"session-42"/);
  assert.equal(parseJournal(continuationMarkdown).length, 1);
});

test("UTC journal date and mixed legacy entries preserve instant ordering", () => {
  assert.deepEqual(localDateTime(new Date("2026-10-30T00:30:00+14:00")), {
    day: "2026-10-29", timestamp: Date.parse("2026-10-30T00:30:00+14:00"),
  });
  const turn = { agent: "codex" as const, sessionId: "s", turnId: "new", user: "a", assistant: "b" };
  const newEntry = renderEntry(turn, "- New task\n- Completed task", Date.parse("2026-10-29T02:00:00Z"));
  const oldEntry = renderEntry({ ...turn, turnId: "old" }, "- Old task\n- Completed task", Date.parse("2026-10-29T01:00:00Z"))
    .replace(/"captured_at":\d+/, '"captured_at":"2026-10-28T22:00:00-03:00"');
  const merged = mergeJournals("2026-10-29", journalHeader(day) + newEntry, journalHeader(day) + oldEntry);
  assert.deepEqual(parseJournal(merged).map((entry) => entry.metadata.turn_id), ["old", "new"]);
});

test("journal lock serializes concurrent writers", async () => {
  const dir = mkdtempSync(join(tmpdir(), "kioku-journal-lock-"));
  const path = join(dir, "day.md");
  try {
    writeFileSync(path, "0");
    await Promise.all(Array.from({ length: 8 }, () => withJournalLock(path, async () => {
      const n = Number(readFileSync(path, "utf8"));
      await new Promise((resolve) => setTimeout(resolve, 5));
      writeJournalAtomic(path, String(n + 1));
    })));
    assert.equal(readFileSync(path, "utf8"), "8");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("Claude Stop hook is fast and idempotent", () => {
  const dir = mkdtempSync(join(tmpdir(), "kioku-journal-hook-"));
  try {
    installClaudeMemoryCaptureHook(dir);
    installClaudeMemoryCaptureHook(dir);
    const hooks = JSON.parse(readFileSync(join(dir, ".claude", "settings.local.json"), "utf8")).hooks.Stop;
    assert.equal(hooks.length, 1);
    assert.equal(hooks[0].hooks[0].timeout, 10);
    assert.equal(hooks[0].hooks[0].async, undefined);
    assert.match(hooks[0].hooks[0].command, /memory-capture --agent claude_code$/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
