import { test } from "node:test";
import assert from "node:assert/strict";
import { renderTable } from "./table.js";

test("renderTable includes headers and cell values", () => {
  const out = renderTable(["Name", "Kind"], [["alpha", "repo"], ["beta", "folder"]]);
  for (const s of ["Name", "Kind", "alpha", "repo", "beta", "folder"]) {
    assert.match(out, new RegExp(s));
  }
});

test("plain fallback (no TTY) has no vertical borders", () => {
  const out = renderTable(["A"], [["x"]]);
  assert.doesNotMatch(out, /│/);
});
