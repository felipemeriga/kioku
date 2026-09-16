/**
 * Server-side watcher registration — replaces the old push hooks.
 *
 * `kioku init` (any computer, same repo — registration is idempotent on the
 * server) wires the repo into the watcher: the backend keeps ONE ssh keypair
 * per user (generated server-side; the private key never leaves the backend)
 * and polls the principal branch twice a day, re-indexing graph + code
 * chunks when it moves. If the key can't read the repo yet, we print the
 * public key and exactly what to do with it.
 */

import { execFileSync } from "node:child_process";

import { ok, info, warn } from "./banner.js";

/** Normalize any GitHub-ish remote to the SSH form the watcher key uses. */
export function toSshRemote(remoteUrl: string): string {
  const https = /^https?:\/\/([^/]+)\/(.+?)(\.git)?$/.exec(remoteUrl);
  if (https) return `git@${https[1]}:${https[2]}.git`;
  return remoteUrl; // already ssh (git@host:owner/repo.git) or exotic — pass through
}

export function detectDefaultBranch(repoRoot: string): string {
  try {
    const ref = execFileSync(
      "git",
      ["symbolic-ref", "refs/remotes/origin/HEAD"],
      { cwd: repoRoot, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    ).trim();
    const m = /refs\/remotes\/origin\/(.+)$/.exec(ref);
    if (m) return m[1];
  } catch {
    // fall through
  }
  for (const candidate of ["main", "master"]) {
    try {
      execFileSync(
        "git",
        ["show-ref", "--verify", `refs/remotes/origin/${candidate}`],
        { cwd: repoRoot, stdio: "ignore" }
      );
      return candidate;
    } catch {
      // try next
    }
  }
  return "main";
}

interface RegisterArgs {
  repoRoot: string;
  base: string;
  apiKey: string;
  folderId: string;
  remoteUrl: string | null | undefined;
}

export async function registerWithWatcher(args: RegisterArgs): Promise<void> {
  if (!args.remoteUrl) {
    info("No git remote — skipping watcher registration (local-only repo).");
    return;
  }
  const remote = toSshRemote(args.remoteUrl);
  const branch = detectDefaultBranch(args.repoRoot);
  const headers = {
    Authorization: `Bearer ${args.apiKey}`,
    "Content-Type": "application/json",
  };

  let publicKey = "";
  let fingerprint = "";
  let created = false;
  try {
    const res = await fetch(`${args.base}/api/watcher/key`, {
      method: "POST",
      headers,
    });
    if (!res.ok) throw new Error(`${res.status}`);
    const body = (await res.json()) as {
      public_key: string;
      fingerprint: string;
      created: boolean;
    };
    publicKey = body.public_key;
    fingerprint = body.fingerprint;
    created = body.created;
  } catch (err) {
    warn(
      "Couldn't reach the watcher service — repo not registered.",
      err instanceof Error ? err.message : String(err)
    );
    return;
  }

  try {
    const res = await fetch(`${args.base}/api/watcher/repos`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        folder_id: args.folderId,
        remote_url: remote,
        branch,
      }),
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  } catch (err) {
    warn(
      "Watcher registration failed.",
      err instanceof Error ? err.message : String(err)
    );
    return;
  }

  // Can the key actually read the repo? Real ls-remote, server-side.
  try {
    const res = await fetch(`${args.base}/api/watcher/test-access`, {
      method: "POST",
      headers,
      body: JSON.stringify({ remote_url: remote, branch }),
    });
    const body = (await res.json()) as { ok: boolean; error?: string };
    if (body.ok) {
      ok(
        `Watcher active — ${remote} (${branch}) re-indexes automatically ` +
          "when it changes."
      );
      return;
    }
  } catch {
    // fall through to instructions
  }

  warn(
    created
      ? "Watcher key created, but it can't read this repo yet."
      : "The watcher key can't read this repo yet."
  );
  console.log(
    [
      "",
      "  Give kioku's watcher read access (one-time, ~30s):",
      "  1. Copy this public key:",
      "",
      `     ${publicKey}`,
      "",
      `     (fingerprint ${fingerprint})`,
      "  2. GitHub → Settings → SSH and GPG keys → New SSH key → paste.",
      "     For SAML/SSO organizations: Configure SSO → Authorize the org.",
      "     If you have repo admin: prefer Settings → Deploy keys on the repo",
      "     (read-only) instead of an account key.",
      "  3. Re-run `kioku init` (or `kioku doctor`) to verify access.",
      "",
    ].join("\n")
  );
}
