import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer, type Server } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { registerWithMihari, toSshRemote } from "./mihari.js";
import { writeConfig } from "./config.js";

test("Mihari registration uses the renamed API without changing git identity", async () => {
  const calls: Array<{ url: string; body: unknown; authorization: string }> =
    [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({
      url: String(input),
      body: init?.body ? JSON.parse(String(init.body)) : null,
      authorization: (init?.headers as Record<string, string>).Authorization,
    });
    const body =
      calls.length === 1
        ? {
            public_key: "ssh-ed25519 existing-key",
            fingerprint: "SHA256:test",
            created: false,
          }
        : { ok: true };
    return Response.json(body);
  };
  try {
    await registerWithMihari({
      repoRoot: "/",
      base: "https://kioku.example",
      apiKey: "rag_test",
      folderId: "folder-id",
      remoteUrl: "https://github.com/example/project.git",
    });
    assert.deepEqual(
      calls.map((call) => call.url),
      [
        "https://kioku.example/api/mihari/key",
        "https://kioku.example/api/mihari/repos",
        "https://kioku.example/api/mihari/test-access",
      ],
    );
    assert.ok(calls.every((call) => call.authorization === "Bearer rag_test"));
    assert.deepEqual(calls[1].body, {
      folder_id: "folder-id",
      remote_url: "git@github.com:example/project.git",
      branch: "main",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Mihari preserves SSH remotes", () => {
  assert.equal(
    toSshRemote("git@github.com:example/project.git"),
    "git@github.com:example/project.git",
  );
});

async function withOwnerConfig(base: string, action: () => Promise<void>) {
  const directory = mkdtempSync(join(tmpdir(), "kioku-mihari-owner-"));
  const previousDir = process.env.XDG_CONFIG_HOME;
  const previousBase = process.env.KIOKU_API_BASE;
  process.env.XDG_CONFIG_HOME = directory;
  delete process.env.KIOKU_API_BASE;
  writeConfig({ api_base: base, access_token: "owner-session-fixture" });
  try {
    await action();
  } finally {
    if (previousDir === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previousDir;
    if (previousBase === undefined) delete process.env.KIOKU_API_BASE;
    else process.env.KIOKU_API_BASE = previousBase;
    rmSync(directory, { recursive: true, force: true });
  }
}

test("owner session is sent only to the exact configured API base", async () => {
  const originalFetch = globalThis.fetch;
  try {
    await withOwnerConfig("https://trusted.example", async () => {
      for (const base of [
        "https://trusted.example/",
        "https://foreign.example",
        "https://trusted.example/proxy",
        "http://trusted.example",
        "https://user@trusted.example",
      ]) {
        const calls: RequestInit[] = [];
        globalThis.fetch = async (_input, init) => {
          calls.push(init!);
          return Response.json(
            calls.length === 1
              ? {
                  public_key: "public",
                  fingerprint: "fingerprint",
                  created: false,
                }
              : { ok: true },
          );
        };
        await registerWithMihari({
          repoRoot: "/",
          base,
          apiKey: "rag_fixture",
          folderId: "folder",
          remoteUrl: "git@github.com:example/repo.git",
        });
        assert.equal(calls.length, 3);
        for (const call of calls) {
          assert.equal(call.redirect, "error");
          assert.equal(
            (call.headers as Record<string, string>)[
              "X-Kioku-Owner-Authorization"
            ],
            base === "https://trusted.example/"
              ? "Bearer owner-session-fixture"
              : undefined,
          );
        }
      }
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  return `http://127.0.0.1:${address.port}`;
}

async function close(server: Server) {
  server.closeAllConnections();
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  );
}

test("a redirect never forwards the owner session to another server", async () => {
  let forwarded = 0;
  const destination = createServer((_request, response) => {
    forwarded++;
    response.end("unexpected");
  });
  const destinationBase = await listen(destination);
  let receivedOwner: string | string[] | undefined;
  const source = createServer((request, response) => {
    receivedOwner = request.headers["x-kioku-owner-authorization"];
    response.writeHead(302, { Location: destinationBase + "/stolen" });
    response.end();
  });
  const sourceBase = await listen(source);
  try {
    await withOwnerConfig(sourceBase, async () => {
      await registerWithMihari({
        repoRoot: "/",
        base: sourceBase,
        apiKey: "rag_fixture",
        folderId: "folder",
        remoteUrl: "git@github.com:example/repo.git",
      });
    });
    assert.equal(receivedOwner, "Bearer owner-session-fixture");
    assert.equal(forwarded, 0);
  } finally {
    await close(source);
    await close(destination);
  }
});
