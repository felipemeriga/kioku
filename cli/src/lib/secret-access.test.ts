import test from "node:test";
import assert from "node:assert/strict";
import {
  parseBindings,
  secureApiBase,
  secretRequest,
} from "./secret-access.js";
const id = "11111111-1111-4111-8111-111111111111";
test("accepts only explicit unique versioned bindings", () => {
  assert.deepEqual(parseBindings([id + "@2"]), [
    { binding_id: id, revision: 2 },
  ]);
  for (const list of [
    [],
    [id],
    [id + "@0"],
    [id + "@2", id + "@3"],
    [id + "@NaN"],
  ])
    assert.throws(() => parseBindings(list));
});
test("protects device credential transport", () => {
  assert.equal(
    secureApiBase("https://kioku.example").origin,
    "https://kioku.example",
  );
  assert.equal(secureApiBase("http://localhost:8000").hostname, "localhost");
  for (const url of [
    "http://example.com",
    "https://a:b@example.com",
    "https://example.com/path",
    "https://example.com?token=x",
  ])
    assert.throws(() => secureApiBase(url));
});
test("does not surface server body with credentials on errors", async () => {
  const saved = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response("synthetic-hidden-error", { status: 500 });
  try {
    await assert.rejects(
      secretRequest(
        "https://example.com",
        "/api/secret-access/resolve",
        "ksd_fake",
        {},
      ),
      (e) =>
        e instanceof Error && !e.message.includes("synthetic-hidden-error"),
    );
  } finally {
    globalThis.fetch = saved;
  }
});
test("redirection disabled for secret requests", async () => {
  const saved = globalThis.fetch;
  globalThis.fetch = async (_url, options) => {
    assert.equal(options?.redirect, "error");
    assert.equal(options?.cache, "no-store");
    return Response.json({ ok: true });
  };
  try {
    assert.deepEqual(
      await secretRequest("https://example.com", "/api/test", "ksd_fake"),
      { ok: true },
    );
  } finally {
    globalThis.fetch = saved;
  }
});
