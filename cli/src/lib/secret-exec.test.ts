import test from "node:test";
import assert from "node:assert/strict";
import { createSecretRedactor, buildSecretEnvironment } from "./secret-exec.js";
import { once } from "node:events";

test("filters complete, split, adjacent, multiline and encoded secrets", async () => {
  const secret = "fake:/credential\nvalue";
  const filter = createSecretRedactor([secret]);
  let out = "";
  filter.on("data", (c) => (out += c));
  const input =
    "before " +
    secret +
    secret +
    " " +
    encodeURIComponent(secret) +
    " " +
    JSON.stringify(secret).slice(1, -1) +
    " after";
  for (const c of Buffer.from(input)) filter.write(Buffer.from([c]));
  filter.end();
  await once(filter, "end");
  assert.equal(out, "before [redacted][redacted] [redacted] [redacted] after");
});
test("keeps UTF8 intact and emits nonsecret output before stream ends", () => {
  const f = createSecretRedactor(["abcdef"]);
  let out = "";
  f.on("data", (c) => (out += c));
  for (const c of Buffer.from("hello 世界 " + ".".repeat(50)))
    f.write(Buffer.from([c]));
  assert.match(out, /hello 世界/);
  f.end();
});
test("removes inherited credentials without mutating parent or build settings", () => {
  const parent = {
    PATH: "/bin",
    MONGO_URI: "old",
    MONGODB_URL: "old2",
    LD_PRELOAD: "bad",
    NODE_OPTIONS: "bad",
  };
  const env = buildSecretEnvironment(parent, { MONGO_URI: "fake-new" }, [
    "MONGO_URI",
    "MONGODB_URL",
  ]);
  assert.equal(env.MONGO_URI, "fake-new");
  assert.equal(env.MONGODB_URL, undefined);
  assert.equal(env.PATH, "/bin");
  assert.equal(env.LD_PRELOAD, undefined);
  assert.equal(env.NODE_OPTIONS, undefined);
  assert.equal(parent.MONGO_URI, "old");
});
test("refuses dangerous, invalid or oversized mappings", () => {
  for (const values of [
    { LD_PRELOAD: "fake" },
    { NODE_OPTIONS: "fake" },
    { "BAD-NAME": "fake" },
    { MONGO_URI: "a\0b" },
    { MONGO_URI: "x".repeat(65537) },
  ] as Record<string, string>[])
    assert.throws(() => buildSecretEnvironment({}, values, []));
  assert.throws(() => createSecretRedactor([""]));
});

test("executes once without shell interpolation and filters both output streams", async () => {
  const { Writable } = await import("node:stream");
  const { runSecretCommand } = await import("./secret-exec.js");
  let output = "";
  const stream = new Writable({
    write(c, _e, cb) {
      output += c.toString();
      cb();
    },
  });
  const result = await runSecretCommand(
    [
      process.execPath,
      "-e",
      "process.stdout.write(process.env.TEST_CREDENTIAL);process.stderr.write(process.env.TEST_CREDENTIAL);process.exitCode=7",
    ],
    {
      invocation_id: "test",
      environment: { TEST_CREDENTIAL: "synthetic-not-real" },
      clear_env: [],
      credential_expires_at: null,
    },
    { stdout: stream, stderr: stream },
  );
  assert.equal(result, 7);
  assert.equal(output, "[redacted][redacted]");
});
test("does not start a process with expired credentials", async () => {
  const { runSecretCommand } = await import("./secret-exec.js");
  await assert.rejects(
    runSecretCommand(["definitely-not-a-real-command"], {
      invocation_id: "test",
      environment: { TEST_CREDENTIAL: "fake" },
      clear_env: [],
      credential_expires_at: "2020-01-01T00:00:00Z",
    }),
    /expired/,
  );
});
