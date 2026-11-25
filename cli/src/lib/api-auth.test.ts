import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ApiError, whoami } from "./api.js";
import { clearAuth, readConfig, writeConfig } from "./config.js";
import { doctor } from "../commands/doctor.js";
import { status } from "../commands/status.js";

async function fixture(
  action: (calls: string[], output: string[]) => Promise<void>,
  refresh: () => Response | Promise<Response> = () =>
    Response.json({
      access_token: "renewed",
      refresh_token: "rotated",
      expires_in: 3600,
    })
) {
  const root = mkdtempSync(join(tmpdir(), "kioku-auth-"));
  const env = { ...process.env },
    cwd = process.cwd(),
    fetch = globalThis.fetch,
    log = console.log;
  const calls: string[] = [],
    output: string[] = [];
  process.env.XDG_CONFIG_HOME = root;
  process.env.KIOKU_API_BASE = "https://api.example";
  process.env.KIOKU_MCP_URL = "https://mcp.example";
  process.chdir(root);
  writeConfig({
    api_base: "https://api.example",
    access_token: "expired",
    refresh_token: "saved-refresh",
    email: "test@example.com",
    user_id: "user",
    expires_at: 1,
  });
  globalThis.fetch = async (input, init) => {
    const url = String(input);
    calls.push(url);
    if (url.endsWith("/auth-config"))
      return Response.json({
        supabase_url: "https://auth.example",
        supabase_anon_key: "public",
      });
    if (url.includes("grant_type=refresh_token")) return refresh();
    if (url.endsWith("/health")) return Response.json({ status: "ok" });
    const token = (init?.headers as Record<string, string>).Authorization;
    return token === "Bearer renewed"
      ? Response.json({ user_id: "user", root_folders: [] })
      : Response.json({ detail: "Token expired" }, { status: 401 });
  };
  console.log = (...args) => {
    output.push(args.join(" "));
  };
  try {
    await action(calls, output);
  } finally {
    globalThis.fetch = fetch;
    console.log = log;
    process.chdir(cwd);
    process.env = env;
    rmSync(root, { recursive: true, force: true });
  }
}

test("doctor silently renews expired login and persists rotated credentials", async () => {
  await fixture(async (calls, output) => {
    await doctor();
    assert.equal(calls.filter((x) => x.includes("grant_type")).length, 1);
    assert.equal(readConfig().refresh_token, "rotated");
    assert.ok(readConfig().expires_at! > Date.now() / 1000 + 3500);
    assert.doesNotMatch(output.join("\n"), /Session expired|Run: kioku login/);
  });
});

test("parallel calls renew once and both replay successfully", async () => {
  await fixture(async (calls) => {
    const results = await Promise.all([whoami(), whoami()]);
    assert.ok(results.every((x) => x.user_id === "user"));
    assert.equal(calls.filter((x) => x.includes("grant_type")).length, 1);
  });
});

for (const code of [429, 503])
  test(`refresh HTTP ${code} keeps login and never asks to reauthenticate`, async () => {
    await fixture(
      async (_calls, output) => {
        await status();
        assert.doesNotMatch(
          output.join("\n"),
          /Session expired|run kioku login|Run: kioku login/
        );
        assert.match(output.join("\n"), /retry/);
        assert.equal(readConfig().refresh_token, "saved-refresh");
      },
      () =>
        Response.json({ message: "private provider details" }, { status: code })
    );
  });

test("network failure stays retryable without leaking provider errors", async () => {
  await fixture(
    async () => {
      await assert.rejects(
        whoami(),
        (err: unknown) =>
          err instanceof ApiError &&
          err.kind === "unreachable" &&
          !err.message.includes("private")
      );
      assert.equal(readConfig().access_token, "expired");
    },
    () => {
      throw new Error("private provider details");
    }
  );
});

test("revoked refresh token asks for login", async () => {
  await fixture(
    async () => {
      await assert.rejects(
        whoami(),
        (err: unknown) =>
          err instanceof ApiError &&
          err.kind === "unauthorized" &&
          err.hint === "Run: kioku login"
      );
    },
    () => Response.json({ code: "refresh_token_not_found" }, { status: 400 })
  );
});

test("permission rejection does not rotate credentials or claim expiry", async () => {
  await fixture(async (calls) => {
    globalThis.fetch = async (input) => {
      calls.push(String(input));
      return Response.json({ detail: "Forbidden" }, { status: 403 });
    };
    await assert.rejects(
      whoami(),
      (err: unknown) =>
        err instanceof ApiError &&
        err.kind === "http" &&
        err.status === 403 &&
        !err.hint
    );
    assert.equal(calls.length, 1);
    assert.equal(readConfig().refresh_token, "saved-refresh");
  });
});

test("logout during renewal is not undone by its late response", async () => {
  await fixture(
    async () => {
      await assert.rejects(whoami(), ApiError);
      assert.equal(readConfig().access_token, undefined);
      assert.equal(readConfig().refresh_token, undefined);
    },
    () => {
      clearAuth();
      return Response.json({
        access_token: "renewed",
        refresh_token: "rotated",
      });
    }
  );
});

test("malformed successful refresh retains original credentials", async () => {
  await fixture(
    async () => {
      await assert.rejects(
        whoami(),
        (err: unknown) => err instanceof ApiError && err.kind === "http"
      );
      assert.equal(readConfig().refresh_token, "saved-refresh");
    },
    () => Response.json({ access_token: "incomplete" })
  );
});

test("a temporary refresh failure can recover on the next command", async () => {
  let attempts = 0;
  await fixture(
    async () => {
      await assert.rejects(whoami(), ApiError);
      assert.equal((await whoami()).user_id, "user");
      assert.equal(attempts, 2);
    },
    () =>
      ++attempts === 1
        ? Response.json({}, { status: 503 })
        : Response.json({ access_token: "renewed", refresh_token: "rotated" })
  );
});

test("a login changed during renewal wins over the late refresh", async () => {
  await fixture(
    async () => {
      await whoami();
      assert.equal(readConfig().refresh_token, "new-login-refresh");
    },
    () => {
      writeConfig({
        ...readConfig(),
        access_token: "renewed",
        refresh_token: "new-login-refresh",
      });
      return Response.json({
        access_token: "stale-response",
        refresh_token: "stale-refresh",
      });
    }
  );
});
