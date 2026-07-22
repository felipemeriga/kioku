import { test } from "node:test";
import assert from "node:assert/strict";
import { buildMenu } from "./home.js";

const base = { apiBase: "http://x", inRepo: false, repoWired: false };

test("signed out → only login + quit", () => {
  const items = buildMenu({ ...base, signedIn: false });
  assert.deepEqual(items.map((i) => i.value), ["login", "quit"]);
});

test("signed in, not in repo → no init, no briefing", () => {
  const vals = buildMenu({ ...base, signedIn: true }).map((i) => i.value);
  assert.ok(vals.includes("ls") && vals.includes("search") && vals.includes("status"));
  assert.ok(!vals.includes("init"));
  assert.ok(!vals.includes("briefing"));
  assert.ok(vals.includes("logout") && vals.includes("quit"));
});

test("in unwired repo → init offered", () => {
  const vals = buildMenu({ ...base, signedIn: true, inRepo: true, repoWired: false }).map((i) => i.value);
  assert.ok(vals.includes("init"));
  assert.ok(!vals.includes("briefing"));
});

test("in wired repo → briefing offered, init hidden", () => {
  const vals = buildMenu({ ...base, signedIn: true, inRepo: true, repoWired: true }).map((i) => i.value);
  assert.ok(vals.includes("briefing"));
  assert.ok(!vals.includes("init"));
});
