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

test("AWS execution cannot inherit another account default chain", () => {
  const env = buildSecretEnvironment(
    {
      PATH: "/bin",
      AWS_PROFILE: "production",
      AWS_REGION: "production-region",
      AWS_CONFIG_FILE: "/private/prod",
      AWS_SESSION_TOKEN: "old",
      AWS_EC2_METADATA_DISABLED: "false",
    },
    {
      AWS_ACCESS_KEY_ID: "synthetic-id",
      AWS_SECRET_ACCESS_KEY: "synthetic-key",
    },
    [],
  );
  assert.equal(env.AWS_PROFILE, undefined);
  assert.equal(env.AWS_REGION, undefined);
  assert.equal(env.AWS_SESSION_TOKEN, undefined);
  assert.equal(env.AWS_CONFIG_FILE, "/dev/null");
  assert.equal(env.AWS_SHARED_CREDENTIALS_FILE, "/dev/null");
  assert.equal(env.AWS_EC2_METADATA_DISABLED, "true");
  assert.throws(() =>
    buildSecretEnvironment({}, { AWS_ACCESS_KEY_ID: "partial" }, []),
  );
  for (const name of ["PATH", "HOME", "COMSPEC", "IFS", "AWS_PROFILE"])
    assert.throws(() => buildSecretEnvironment({}, { [name]: "fake" }, []));
});

test("redactor never splits a non-BMP character at its retained boundary", async () => {
  const f = createSecretRedactor(["abcdef"]);
  let output = "";
  f.on("data", (c) => (output += c));
  f.write("🙂....");
  f.end();
  await once(f, "end");
  assert.equal(output, "🙂....");
});

test(
  "cancellation kills descendants even after group leader closes",
  { timeout: 12000 },
  async () => {
    const { spawn } = await import("node:child_process");
    const inner = `const {spawn}=require('node:child_process');const p=spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});setInterval(()=>{},1000)"],{stdio:'ignore'});setTimeout(()=>process.stdout.write('ready:'+p.pid+'\\n'+' '.repeat(40)),150);process.on('SIGTERM',()=>process.exit(0));setInterval(()=>{},1000);`;
    const module = new URL("./secret-exec.js", import.meta.url).href;
    const outer = `import {runSecretCommand} from ${JSON.stringify(module)};process.exitCode=await runSecretCommand([process.execPath,'-e',${JSON.stringify(inner)}],{invocation_id:'test',environment:{TEST_CREDENTIAL:'synthetic'},clear_env:[],credential_expires_at:null});`;
    const wrapper = spawn(
      process.execPath,
      ["--input-type=module", "-e", outer],
      { stdio: ["ignore", "pipe", "pipe"] },
    );
    let output = "",
      descendant = 0,
      signalled = false;
    wrapper.stdout.on("data", (c) => {
      output += c.toString();
      const found = output.match(/ready:(\d+)/);
      if (found && !signalled) {
        descendant = Number(found[1]);
        signalled = true;
        wrapper.kill("SIGTERM");
      }
    });
    const deadline = setTimeout(() => wrapper.kill("SIGKILL"), 10000);
    try {
      const [code] = await once(wrapper, "close");
      assert.equal(code, 143);
      assert.ok(descendant > 0);
      let alive = true;
      try {
        process.kill(descendant, 0);
        const { execFileSync } = await import("node:child_process");
        const state = execFileSync(
          "ps",
          ["-o", "stat=", "-p", String(descendant)],
          { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
        ).trim();
        alive = !state.startsWith("Z");
      } catch {
        alive = false;
      }
      assert.equal(alive, false);
    } finally {
      clearTimeout(deadline);
      if (descendant)
        try {
          process.kill(descendant, "SIGKILL");
        } catch {
          /* already gone */
        }
      wrapper.kill("SIGKILL");
    }
  },
);
