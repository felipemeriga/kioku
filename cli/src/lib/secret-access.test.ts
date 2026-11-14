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

test("stores devices privately and isolates roots/API origins", async () => {
  const fs = await import("node:fs");
  const os = await import("node:os");
  const path = await import("node:path");
  const { saveSecretDevice, readSecretDevice, forgetSecretDevice } =
    await import("./secret-access.js");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kioku-device-test-"));
  const before = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    const device = {
      root_id: id,
      device_id: "22222222-2222-4222-8222-222222222222",
      device_token: "ksd_synthetic_only",
      expires_at: new Date(Date.now() + 60000).toISOString(),
    };
    saveSecretDevice(device, "https://one.example");
    assert.equal(
      readSecretDevice(id, "https://one.example").device_id,
      device.device_id,
    );
    assert.throws(() => readSecretDevice(id, "https://two.example"));
    const file = path.join(
      dir,
      "kioku",
      "secret-devices",
      fs.readdirSync(path.join(dir, "kioku", "secret-devices"))[0],
    );
    assert.equal(fs.statSync(file).mode & 0o777, 0o600);
    fs.chmodSync(file, 0o644);
    assert.throws(() => readSecretDevice(id, "https://one.example"));
    forgetSecretDevice(id, "https://one.example");
    assert.throws(() => readSecretDevice(id, "https://one.example"));
  } finally {
    if (before === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = before;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
