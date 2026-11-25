import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { historyArguments, integerOption } from "./recall.js";
import { decodeRecallResult, findRecallBinding } from "../lib/recall-mcp.js";

test("weekly recall sends explicit dates, timezone, scope and pagination unchanged", () => {
  assert.deepEqual(
    historyArguments("what did we work on", {
      from: "2026-11-16",
      through: "2026-11-22",
      timezone: "America/Sao_Paulo",
      folder: "cosm",
      asOf: "2026-11-22T23:59:59-03:00",
      order: "latest",
      offset: "10",
      limit: "20",
    }),
    {
      query: "what did we work on",
      from_date: "2026-11-16",
      through_date: "2026-11-22",
      timezone: "America/Sao_Paulo",
      folder: "cosm",
      as_of: "2026-11-22T23:59:59-03:00",
      order: "latest",
      offset: 10,
      limit: 20,
    }
  );
});

test("empty query browses activity and invalid filters fail before requests", () => {
  assert.equal(historyArguments("", {}).query, "");
  assert.throws(() => historyArguments("", { from: "2026-02-30" }));
  assert.throws(() =>
    historyArguments("", { from: "2026-11-22", through: "2026-11-16" })
  );
  assert.throws(() => historyArguments("", { timezone: "Invalid/Zone" }));
  assert.throws(() => historyArguments("", { order: "oldest" }));
  for (const n of ["1.5", "-1", "1x", "51", ""])
    assert.throws(() => integerOption(n, 10, 1, 50));
});

test("recall retains references, pending-index warning and next page", () => {
  const data = {
    status: "ok",
    hits: [{ reference: "opaque-cutoff-reference" }],
    has_more: true,
    next_offset: 10,
    index_pending_objects: 3,
  };
  assert.deepEqual(
    decodeRecallResult({
      content: [{ type: "text", text: JSON.stringify(data) }],
    }),
    data
  );
  assert.throws(
    () =>
      decodeRecallResult({
        content: [
          {
            type: "text",
            text: '{"status":"error","detail":{"code":"evidence_query_timeout"}}',
          },
        ],
      }),
    /evidence_query_timeout/
  );
  assert.throws(
    () =>
      decodeRecallResult({
        isError: true,
        content: [{ type: "text", text: "private diagnostic" }],
      }),
    /MCP tool failed/
  );
  assert.throws(() => decodeRecallResult({ content: [] }));
});

test("nested directories find nearest scope and never skip invalid explicit config", () => {
  const dir = mkdtempSync(join(tmpdir(), "kioku-recall-"));
  try {
    const child = join(dir, "crate");
    mkdirSync(child);
    writeFileSync(
      join(dir, ".mcp.json"),
      JSON.stringify({
        mcpServers: {
          kioku: {
            url: "https://example.test/mcp",
            headers: { Authorization: "Bearer rag_synthetic" },
          },
        },
      })
    );
    assert.equal(findRecallBinding(child).key, "rag_synthetic");
    writeFileSync(join(child, ".mcp.json"), "{}");
    assert.throws(() => findRecallBinding(child), /No valid Kioku/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
