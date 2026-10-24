import assert from "node:assert/strict";
import { test } from "node:test";

import { registerWithMihari, toSshRemote } from "./mihari.js";

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
      ]
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
    "git@github.com:example/project.git"
  );
});
