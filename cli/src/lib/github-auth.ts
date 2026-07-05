/**
 * GitHub auth strategy for `agentic-rag init`.
 *
 * The problem: we need a token to sync private repos, but we don't want
 * the user to always paste one. Three fallback tiers, ordered by UX:
 *
 *   1. `gh` CLI already logged in    → we borrow its token
 *   2. GITHUB_TOKEN / GH_TOKEN env   → we use whichever is set
 *   3. Interactive paste from browser → last resort
 *
 * The token is never stored on disk here. We hand it to the backend
 * once (POST /api/github/connect); Supabase stores it encrypted via
 * services/crypto.py. Re-init runs the same tier detection.
 *
 * Public repos skip auth entirely — we detect visibility first.
 */

import { execFileSync } from "node:child_process";
import { input, password, select, confirm } from "@inquirer/prompts";
import kleur from "kleur";
import { info, warn } from "./banner.js";

export type TokenSource = "gh-cli" | "env" | "pasted" | "none";

export interface RepoVisibility {
  visibility: "public" | "private" | "unknown";
  /** True if the anon check hit a rate limit — we can't be sure. */
  rateLimited?: boolean;
}

/** Anon fetch to /repos/{o}/{r}. 200 → public, 404 → private (or missing).
 *  We can't distinguish 404-private from 404-missing until we have a
 *  token, so we return 'unknown' in the 404 case and let the auth flow
 *  decide. */
export async function detectRepoVisibility(
  owner: string,
  repo: string,
): Promise<RepoVisibility> {
  try {
    const res = await fetch(
      `https://api.github.com/repos/${owner}/${repo}`,
      {
        headers: {
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
        },
      },
    );
    if (res.status === 200) return { visibility: "public" };
    if (res.status === 404) return { visibility: "unknown" };
    if (res.status === 403) return { visibility: "unknown", rateLimited: true };
    return { visibility: "unknown" };
  } catch {
    return { visibility: "unknown" };
  }
}

/** Ping /repos/{o}/{r} with a token. 200 = the token grants access. */
export async function verifyTokenAccess(
  owner: string,
  repo: string,
  token: string,
): Promise<boolean> {
  try {
    const res = await fetch(
      `https://api.github.com/repos/${owner}/${repo}`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
        },
      },
    );
    return res.status === 200;
  } catch {
    return false;
  }
}

/** Try `gh auth token`. Returns null if gh isn't installed or isn't logged in. */
export function ghCliToken(): string | null {
  try {
    const out = execFileSync("gh", ["auth", "token"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 3000,
    });
    const t = out.trim();
    return t && (t.startsWith("gh") || t.startsWith("ghp_") || t.startsWith("github_pat_"))
      ? t
      : null;
  } catch {
    return null;
  }
}

/** GitHub docs URL that pre-fills the right scopes so users don't
 *  have to hunt through the settings screen. */
function patCreationUrl(owner: string, repo: string): string {
  const params = new URLSearchParams({
    description: `agentic-rag sync — ${owner}/${repo}`,
    scopes: "repo,read:org",
  });
  return `https://github.com/settings/tokens/new?${params.toString()}`;
}

/**
 * Resolve a token for the given repo. Walks the tiers, verifying each
 * candidate before returning. If everything fails, returns null with a
 * TokenSource explanation.
 */
export async function resolveGitHubToken(args: {
  owner: string;
  repo: string;
  /** If true, skip prompts and return null when no automatic tier hits.
   *  Used with `--yes` to keep init non-interactive. */
  nonInteractive?: boolean;
  /** Explicit token from --github-token flag. If set + verifies, we use it. */
  explicit?: string;
}): Promise<{ token: string | null; source: TokenSource }> {
  const { owner, repo } = args;

  // 0. Explicit flag wins
  if (args.explicit) {
    const explicit = args.explicit.trim();
    if (explicit) {
      const ok = await verifyTokenAccess(owner, repo, explicit);
      if (ok) return { token: explicit, source: "pasted" };
      warn("Provided token doesn't grant access to that repo.");
    }
  }

  // 1. gh CLI
  const gh = ghCliToken();
  if (gh) {
    const ok = await verifyTokenAccess(owner, repo, gh);
    if (ok) {
      info(`Using gh CLI token  ${kleur.dim("(github user " + await ghUser(gh) + ")")}`);
      return { token: gh, source: "gh-cli" };
    } else {
      info(`gh CLI is logged in but doesn't have access to ${owner}/${repo}.`);
    }
  }

  // 2. env vars
  const envToken = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  if (envToken) {
    const ok = await verifyTokenAccess(owner, repo, envToken);
    if (ok) {
      info(`Using $${process.env.GITHUB_TOKEN ? "GITHUB_TOKEN" : "GH_TOKEN"}`);
      return { token: envToken, source: "env" };
    }
  }

  if (args.nonInteractive) {
    return { token: null, source: "none" };
  }

  // 3. interactive fallback
  const choice = await select<"paste" | "skip">({
    message: `${owner}/${repo} needs a token. What now?`,
    choices: [
      {
        name: "Paste a Personal Access Token",
        value: "paste",
        description: `Opens a browser to create one with the right scopes.`,
      },
      {
        name: "Skip GitHub sync for now (public-only briefing)",
        value: "skip",
      },
    ],
  });

  if (choice === "skip") {
    return { token: null, source: "none" };
  }

  info(`Create a token here: ${kleur.underline(patCreationUrl(owner, repo))}`);
  info(kleur.dim("The scopes 'repo' and 'read:org' are pre-selected."));

  // Attempt to open the browser silently — best-effort, don't block.
  tryOpenBrowser(patCreationUrl(owner, repo));

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const pasted = (
      await password({
        message: attempt === 0
          ? "Paste your PAT:"
          : "That token didn't grant access. Try again:",
        mask: "*",
      })
    ).trim();
    if (!pasted) return { token: null, source: "none" };
    const ok = await verifyTokenAccess(owner, repo, pasted);
    if (ok) return { token: pasted, source: "pasted" };
  }
  warn("Skipping GitHub sync after 3 failed attempts.");
  return { token: null, source: "none" };
}

/** Grab the authenticated user's login so we can show it in the picker. */
async function ghUser(token: string): Promise<string> {
  try {
    const res = await fetch("https://api.github.com/user", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return "?";
    const body = (await res.json()) as { login?: string };
    return body.login ?? "?";
  } catch {
    return "?";
  }
}

/** Best-effort browser open. macOS: open, Linux: xdg-open, Windows: start. */
function tryOpenBrowser(url: string): void {
  const cmd =
    process.platform === "darwin"
      ? ["open", url]
      : process.platform === "win32"
      ? ["cmd", "/c", "start", url]
      : ["xdg-open", url];
  try {
    execFileSync(cmd[0], cmd.slice(1), {
      stdio: "ignore",
      timeout: 2000,
    });
  } catch {
    // No browser (headless server, WSL edge cases). Not worth complaining
    // — we already printed the URL for copy/paste.
  }
}
