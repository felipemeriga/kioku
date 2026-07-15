import { test } from "node:test";
import assert from "node:assert/strict";
import { panel } from "./panel.js";

test("panel includes title and body text", () => {
  const out = panel({ title: "Status", body: "signed in" });
  assert.match(out, /Status/);
  assert.match(out, /signed in/);
});

test("panel plain fallback (no TTY) has no box-drawing chars", () => {
  const out = panel({ title: "T", body: "b" });
  // node --test has no TTY, so colorEnabled() is false → plain
  assert.doesNotMatch(out, /[╭╮╰╯│─]/);
  assert.match(out, /T/);
  assert.match(out, /b/);
});
