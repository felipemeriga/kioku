import { test, describe } from "node:test";
import assert from "node:assert/strict";
import {
  existsSync,
  readFileSync,
  statSync,
  writeFileSync,
  mkdtempSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { execFileSync } from "node:child_process";
import { parse as yaml } from "yaml";
import { parse as toml } from "smol-toml";
import {
  prepareSecretDeliveries,
  renderSecretConfig,
  cleanupStaleSecretFiles,
} from "./secret-delivery.js";
describe(
  "POSIX protected delivery",
  { skip: process.platform === "win32" },
  () => {
    const secret = 'synthetic-quote"\\\n雪-canary';
    for (const format of ["json", "yaml", "toml"] as const)
      test(`${format} real configuration consumer, original immutable and protected cleanup`, () => {
        const template =
          format === "json"
            ? '{"db":{"password":"placeholder"}}'
            : format === "yaml"
            ? "db:\n  password: placeholder\n"
            : '[db]\npassword = "placeholder"\n';
        const original = template;
        const p = prepareSecretDeliveries([
          {
            kind: "file",
            format,
            source_template: template,
            patches: [{ path: ["db", "password"], value: secret }],
            destination: { kind: "env", name: "APP_CONFIG" },
          },
        ]);
        try {
          const path = p.environment.APP_CONFIG;
          assert.equal(statSync(path).mode & 0o777, 0o600);
          assert.equal(statSync(p.directory).mode & 0o777, 0o700);
          const copied = execFileSync(
            process.execPath,
            [
              "-e",
              "process.stdout.write(require('fs').readFileSync(process.env.APP_CONFIG,'utf8'))",
            ],
            { env: { ...process.env, ...p.environment }, encoding: "utf8" }
          );
          const parsed =
            format === "json"
              ? JSON.parse(copied)
              : format === "yaml"
              ? yaml(copied)
              : toml(copied);
          assert.equal(parsed.db.password, secret);
          assert.equal(template, original);
        } finally {
          p.cleanup();
        }
        assert.equal(existsSync(p.directory), false);
      });
    test("unsafe config paths and malformed templates reject without leaking values", () => {
      for (const path of [
        ["__proto__", "polluted"],
        ["missing", "child"],
        ["constructor"],
      ])
        assert.throws(
          () =>
            renderSecretConfig("json", '{"db":{}}', [{ path, value: secret }]),
          /Invalid or unsupported/
        );
      assert.throws(() =>
        renderSecretConfig("yaml", "bad: [", [{ path: ["bad"], value: secret }])
      );
    });
    test("raw argv needs explicit acknowledgement, file paths stay separate arguments", () => {
      assert.throws(() =>
        prepareSecretDeliveries([
          { kind: "argv", arguments: [{ kind: "secret", value: secret }] },
        ])
      );
      const p = prepareSecretDeliveries(
        [
          {
            kind: "argv",
            arguments: [
              { kind: "literal", value: "--token" },
              { kind: "secret", value: secret },
            ],
          },
        ],
        true
      );
      try {
        assert.deepEqual(p.arguments, ["--token", secret]);
        assert.deepEqual(p.secrets, [secret]);
      } finally {
        p.cleanup();
      }
    });
    test("SSH pins host key and encrypted identity helper supplies exact passphrase without argv", () => {
      const p = prepareSecretDeliveries([
        {
          kind: "ssh",
          host: "localhost",
          user: "test",
          port: 2222,
          host_key:
            "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ7+vWmtUUglk7D/DkcAg7USIIOfv+CjVvEz/6WE2xKJ",
          private_key: "synthetic-private-key",
          passphrase: secret,
        },
      ]);
      try {
        assert.ok(p.ssh?.includes("StrictHostKeyChecking=yes"));
        assert.ok(p.ssh?.includes("IdentityAgent=none"));
        assert.ok(!p.ssh?.some((x) => x.includes(secret)));
        const pass = execFileSync(p.environment.SSH_ASKPASS, [], {
          encoding: "utf8",
        });
        assert.equal(pass, secret);
        assert.equal(statSync(p.environment.SSH_ASKPASS).mode & 0o777, 0o700);
      } finally {
        p.cleanup();
      }
      assert.equal(existsSync(p.directory), false);
    });
    test("stale owned invocation removed after expiry; active invocation retained", () => {
      const p = prepareSecretDeliveries([
        { kind: "env", environment: { TOKEN: secret } },
      ]);
      cleanupStaleSecretFiles();
      assert.ok(existsSync(p.directory));
      writeFileSync(
        join(p.directory, "expiry.json"),
        JSON.stringify({ version: 1, expires: Date.now() - 1 }),
        { mode: 0o600 }
      );
      cleanupStaleSecretFiles();
      assert.ok(!existsSync(p.directory));
    });

    test("real encrypted OpenSSH private key decrypts noninteractively through invocation helper", () => {
      const dir = mkdtempSync(join(tmpdir(), "kioku-key-test-"));
      try {
        const key = join(dir, "identity"),
          pass = "synthetic-safe-passphrase";
        execFileSync(
          "/usr/bin/ssh-keygen",
          ["-q", "-t", "ed25519", "-N", pass, "-f", key],
          { stdio: "ignore" }
        );
        const expected = readFileSync(key + ".pub", "utf8")
          .trim()
          .split(" ")
          .slice(0, 2)
          .join(" ");
        const p = prepareSecretDeliveries([
          {
            kind: "ssh",
            host: "localhost",
            user: "test",
            port: 2222,
            host_key: expected,
            private_key: readFileSync(key, "utf8"),
            passphrase: pass,
          },
        ]);
        try {
          const identity = p.ssh![p.ssh!.indexOf("-i") + 1];
          const actual = execFileSync(
            "/usr/bin/ssh-keygen",
            ["-y", "-f", identity],
            {
              env: { ...process.env, ...p.environment },
              stdio: ["ignore", "pipe", "pipe"],
              encoding: "utf8",
              timeout: 5000,
            }
          );
          assert.equal(
            actual.trim().split(" ").slice(0, 2).join(" "),
            expected
          );
        } finally {
          p.cleanup();
        }
      } finally {
        rmSync(dir, { recursive: true, force: true });
      }
    });

    test("AWS credential file keeps complete pair and isolates inherited selectors", () => {
      const p = prepareSecretDeliveries([
        {
          kind: "file",
          format: "toml",
          source_template: "[default]\n",
          patches: [
            {
              path: ["default", "aws_access_key_id"],
              value: "synthetic-access",
            },
            {
              path: ["default", "aws_secret_access_key"],
              value: "synthetic-secret-key",
            },
          ],
          destination: { kind: "env", name: "AWS_SHARED_CREDENTIALS_FILE" },
          environment: { AWS_REGION: "us-east-1" },
        },
      ]);
      try {
        assert.equal(p.trustedEnvironment.AWS_EC2_METADATA_DISABLED, "true");
        assert.equal(p.trustedEnvironment.AWS_CONFIG_FILE, "/dev/null");
        assert.equal(p.trustedEnvironment.AWS_REGION, "us-east-1");
        const config = toml(
          readFileSync(p.trustedEnvironment.AWS_SHARED_CREDENTIALS_FILE, "utf8")
        ) as any;
        assert.equal(
          config.default.aws_secret_access_key,
          "synthetic-secret-key"
        );
      } finally {
        p.cleanup();
      }
    });

    test(
      "isolated sshd accepts encrypted identity and rejects mismatched pinned key",
      { timeout: 20000 },
      async (t) => {
        if (!existsSync("/usr/sbin/sshd")) {
          t.skip("isolated sshd unavailable on this runner");
          return;
        }
        const { spawn } = await import("node:child_process");
        const { createServer } = await import("node:net");
        const { Writable } = await import("node:stream");
        const { userInfo } = await import("node:os");
        const { writeFileSync } = await import("node:fs");
        const { runSecretCommand } = await import("./secret-exec.js");
        const server = createServer();
        await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
        const port = (server.address() as any).port;
        await new Promise<void>((r) => server.close(() => r()));
        const dir = mkdtempSync(join(tmpdir(), "kioku-sshd-test-"));
        let daemon: ReturnType<typeof spawn> | undefined;
        try {
          for (const name of ["host", "wrong", "client"])
            execFileSync(
              "/usr/bin/ssh-keygen",
              [
                "-q",
                "-t",
                "ed25519",
                "-N",
                name === "client" ? "synthetic-ssh-passphrase" : "",
                "-f",
                join(dir, name),
              ],
              { stdio: "ignore" }
            );
          writeFileSync(
            join(dir, "authorized"),
            readFileSync(join(dir, "client.pub")),
            { mode: 0o600 }
          );
          writeFileSync(
            join(dir, "config"),
            `Port ${port}\nListenAddress 127.0.0.1\nHostKey ${dir}/host\nPidFile ${dir}/pid\nAuthorizedKeysFile ${dir}/authorized\nPasswordAuthentication no\nUsePAM no\nStrictModes no\nLogLevel ERROR\n`
          );
          try {
            execFileSync("/usr/sbin/sshd", ["-t", "-f", join(dir, "config")], {
              stdio: "ignore",
            });
          } catch {
            t.skip("runner cannot initialize isolated sshd");
            return;
          }
          daemon = spawn(
            "/usr/sbin/sshd",
            ["-D", "-e", "-f", join(dir, "config")],
            { stdio: "ignore" }
          );
          await new Promise((r) => setTimeout(r, 250));
          for (const host of ["host", "wrong"]) {
            const hostkey = readFileSync(join(dir, host + ".pub"), "utf8")
              .trim()
              .split(" ")
              .slice(0, 2)
              .join(" ");
            const p = prepareSecretDeliveries([
              {
                kind: "ssh",
                host: "127.0.0.1",
                user: userInfo().username,
                port,
                host_key: hostkey,
                private_key: readFileSync(join(dir, "client"), "utf8"),
                passphrase: "synthetic-ssh-passphrase",
              },
            ]);
            let output = "";
            const sink = new Writable({
              write(chunk, _encoding, cb) {
                output += chunk;
                cb();
              },
            });
            try {
              const code = await runSecretCommand(
                [...p.ssh!, "printf fixture-ready"],
                {
                  invocation_id: "synthetic",
                  environment: p.environment,
                  clear_env: p.clearEnvironment,
                  credential_expires_at: null,
                },
                { stdout: sink, stderr: sink },
                p
              );
              if (host === "host") {
                assert.equal(code, 0, output);
                assert.match(output, /fixture-ready/);
              } else {
                assert.notEqual(code, 0);
                assert.doesNotMatch(output, /fixture-ready/);
              }
              assert.doesNotMatch(output, /synthetic-ssh-passphrase/);
            } finally {
              p.cleanup();
            }
            assert.equal(existsSync(p.directory), false);
          }
        } finally {
          daemon?.kill("SIGKILL");
          if (daemon)
            await new Promise<void>((r) => {
              if (daemon!.exitCode !== null || daemon!.signalCode !== null) r();
              else daemon!.once("close", () => r());
            });
          rmSync(dir, { recursive: true, force: true });
        }
      }
    );

    test("explicitly acknowledged argv reaches real receiver and output redacts secret", async () => {
      const { Writable } = await import("node:stream");
      const { runSecretCommand } = await import("./secret-exec.js");
      const p = prepareSecretDeliveries(
        [
          {
            kind: "argv",
            arguments: [
              { kind: "literal", value: "--token" },
              { kind: "secret", value: "synthetic-argv-canary" },
            ],
          },
        ],
        true
      );
      let output = "";
      const sink = new Writable({
        write(chunk, _enc, cb) {
          output += chunk;
          cb();
        },
      });
      try {
        const code = await runSecretCommand(
          [
            process.execPath,
            "-e",
            "if(process.argv[1]!=='--token')process.exit(7);process.stdout.write(process.argv[2]);",
            "--",
            ...p.arguments,
          ],
          {
            invocation_id: "synthetic",
            environment: p.environment,
            clear_env: [],
            credential_expires_at: null,
          },
          { stdout: sink, stderr: sink },
          p
        );
        assert.equal(code, 0);
        assert.equal(output, "[redacted]");
      } finally {
        p.cleanup();
      }
    });

    test("stale cleanup never follows invocation symlinks", () => {
      const p = prepareSecretDeliveries([
        { kind: "env", environment: { TOKEN: "synthetic" } },
      ]);
      const target = mkdtempSync(join(tmpdir(), "kioku-unrelated-"));
      const link = join(
        dirname(p.directory),
        "invoke-" + Math.random().toString(36).slice(2, 8).padEnd(6, "x")
      );
      try {
        writeFileSync(join(target, "keep"), "unrelated");
        symlinkSync(target, link);
        cleanupStaleSecretFiles();
        assert.equal(readFileSync(join(target, "keep"), "utf8"), "unrelated");
        assert.ok(existsSync(link));
      } finally {
        rmSync(link, { force: true });
        rmSync(target, { recursive: true, force: true });
        p.cleanup();
      }
    });
  }
);
