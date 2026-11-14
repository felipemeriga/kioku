import test from "node:test";
import assert from "node:assert/strict";
import {
  parseBindings,
  parseUsages,
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
    "https://kioku.example"
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
        {}
      ),
      (e) => e instanceof Error && !e.message.includes("synthetic-hidden-error")
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
      { ok: true }
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
      device.device_id
    );
    assert.throws(() => readSecretDevice(id, "https://two.example"));
    const file = path.join(
      dir,
      "kioku",
      "secret-devices",
      fs.readdirSync(path.join(dir, "kioku", "secret-devices"))[0]
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

test("access commands reject insecure origins before existing auth calls", async () => {
  const { listAccess, enrollAccess } = await import("../commands/access.js");
  const originalBase = process.env.KIOKU_API_BASE,
    fetchBefore = globalThis.fetch;
  let calls = 0;
  process.env.KIOKU_API_BASE = "http://example.com";
  globalThis.fetch = async () => {
    calls++;
    throw Error("should not fetch");
  };
  try {
    await assert.rejects(listAccess({ root: id }), /HTTPS/);
    await assert.rejects(
      enrollAccess({ root: id, fileCredentialStore: true }),
      /HTTPS/
    );
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = fetchBefore;
    if (originalBase === undefined) delete process.env.KIOKU_API_BASE;
    else process.env.KIOKU_API_BASE = originalBase;
  }
});

test("existing user session check forwards cancellation for access commands", async () => {
  const { whoami } = await import("./api.js");
  const old = globalThis.fetch;
  const controller = new AbortController();
  globalThis.fetch = async (_url, options) => {
    assert.equal(options?.signal, controller.signal);
    return Response.json({ user_id: id, root_folders: [] });
  };
  try {
    assert.equal((await whoami(controller.signal)).user_id, id);
  } finally {
    globalThis.fetch = old;
  }
});

test("V2 usage selectors require exact independent usage and credential revisions", () => {
  assert.deepEqual(parseUsages([id + "@2@4"]), [
    { usage_id: id, revision: 2, credential_revision: 4 },
  ]);
  for (const raw of [
    [],
    [id + "@2"],
    [id + "@0@2"],
    [id + "@2@0"],
    [id + "@2@3@4"],
    [id + "@2@4", id + "@3@4"],
  ])
    assert.throws(() => parseUsages(raw));
});

test("V2 resolve uses device-only auth and verifies every exact returned usage revision", async () => {
  const fs = await import("node:fs"),
    os = await import("node:os"),
    path = await import("node:path");
  const { saveSecretDevice, resolveSecretUsages } = await import(
    "./secret-access.js"
  );
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kioku-v2-device-"));
  const oldHome = process.env.XDG_CONFIG_HOME,
    oldBase = process.env.KIOKU_API_BASE,
    oldFetch = globalThis.fetch;
  process.env.XDG_CONFIG_HOME = dir;
  process.env.KIOKU_API_BASE = "https://v2.example";
  try {
    saveSecretDevice(
      {
        root_id: id,
        device_id: "22222222-2222-4222-8222-222222222222",
        device_token: "ksd_synthetic",
        expires_at: new Date(Date.now() + 600000).toISOString(),
      },
      "https://v2.example"
    );
    let wrong = false;
    globalThis.fetch = async (url, options) => {
      assert.equal(
        String(url),
        "https://v2.example/api/secret-access/resolve-v2"
      );
      assert.equal(
        (options?.headers as Record<string, string>).Authorization,
        "Bearer ksd_synthetic"
      );
      const body = JSON.parse(options?.body as string);
      assert.equal(body.allow_raw_secret_argv, false);
      assert.equal(body.usages[0].credential_revision, 4);
      return Response.json({
        invocation_id: body.invocation_id,
        credential_expires_at: null,
        clear_env: [],
        deliveries: [
          {
            usage_id: id,
            revision: wrong ? 3 : 2,
            credential_id: "33333333-3333-4333-8333-333333333333",
            credential_revision: 4,
            kind: "env",
            environment: { TOKEN: "synthetic" },
          },
        ],
      });
    };
    assert.equal(
      (await resolveSecretUsages(id, parseUsages([id + "@2@4"]), false))
        .deliveries.length,
      1
    );
    wrong = true;
    await assert.rejects(
      resolveSecretUsages(id, parseUsages([id + "@2@4"]), false),
      /Invalid access response/
    );
  } finally {
    globalThis.fetch = oldFetch;
    if (oldHome === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = oldHome;
    if (oldBase === undefined) delete process.env.KIOKU_API_BASE;
    else process.env.KIOKU_API_BASE = oldBase;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("secret responses allow bounded multi-resource bundles and reject above four MiB", async () => {
  const old = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      Response.json({ value: "x".repeat(2 * 1048576) });
    assert.equal(
      (
        await secretRequest<{ value: string }>(
          "https://example.com",
          "/api/secret-access/resolve-v2",
          "ksd_synthetic",
          {}
        )
      ).value.length,
      2 * 1048576
    );
    globalThis.fetch = async () =>
      Response.json({ value: "x".repeat(4 * 1048576) });
    await assert.rejects(
      secretRequest(
        "https://example.com",
        "/api/secret-access/resolve-v2",
        "ksd_synthetic",
        {}
      ),
      /exceeds supported limits/
    );
  } finally {
    globalThis.fetch = old;
  }
});
