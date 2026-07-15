/**
 * GitHub auth strategy for `kioku init`.
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

import { execFileSync, spawn } from "node:child_process";
import { input, password, select, confirm } from "@inquirer/prompts";
import kleur from "kleur";
import { info, ok, warn } from "./banner.js";
import { tryOpenBrowser } from "./browser.js";

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
    description: `kioku sync — ${owner}/${repo}`,
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

  // Interactive fallback. Present ALL viable options at once — no
  // hidden fallback ladder. The user picks the least-friction path.
  return interactiveResolve(owner, repo);
}


/**
 * Show all viable auth options as a single menu, keyed off what's
 * detected on the system:
 *   - gh installed + logged in → we skip the menu (already covered above)
 *   - gh installed, not logged in → offer `gh auth login --web` inline
 *   - gh not installed → offer to install it (brew/apt/winget) + then login
 *   - always: paste PAT, skip
 *
 * Retries let users try one path, fail, then try another WITHOUT
 * exiting init.
 */
async function interactiveResolve(
  owner: string,
  repo: string,
): Promise<{ token: string | null; source: TokenSource }> {
  // Loop so if 'gh install' or 'gh login' fails, we bounce back to the
  // menu with the freshly-updated system state.
  for (let round = 0; round < 5; round += 1) {
    const gh = detectGhState();
    const canInstallGh = gh === "not-installed" && !!ghInstallCommand();

    // Build the menu dynamically based on what's actually possible.
    const choices: Array<{ name: string; value: string; description?: string }> = [];
    if (gh === "installed-not-logged-in") {
      choices.push({
        name: `Log into gh CLI  ${kleur.dim("(opens browser, no PAT needed)")}`,
        value: "gh-login",
      });
    }
    if (canInstallGh) {
      const install = ghInstallCommand()!;
      choices.push({
        name: `Install gh CLI  ${kleur.dim("(" + install.label + ")")}`,
        value: "gh-install",
      });
    }
    if (gh === "not-installed" && !canInstallGh) {
      choices.push({
        name: `Install gh CLI manually  ${kleur.dim("(see cli.github.com)")}`,
        value: "gh-install-manual",
      });
    }
    choices.push({
      name: `Paste a Personal Access Token  ${kleur.dim("(browser + copy/paste)")}`,
      value: "paste",
    });
    choices.push({
      name: `Skip GitHub sync  ${kleur.dim("(you can re-run init later)")}`,
      value: "skip",
    });

    const choice = await select<string>({
      message:
        round === 0
          ? `${owner}/${repo} needs GitHub access. Pick a path:`
          : `Still need GitHub access to ${owner}/${repo}. Try another?`,
      choices,
    });

    if (choice === "skip") return { token: null, source: "none" };

    if (choice === "gh-install") {
      const success = await installGhCli();
      if (!success) continue;
      const loginOk = await ghAuthLoginInteractive();
      if (!loginOk) continue;
      const token = ghCliToken();
      if (token && (await verifyTokenAccess(owner, repo, token))) {
        return { token, source: "gh-cli" };
      }
      warn(`gh is now installed + logged in but doesn't have access to ${owner}/${repo}.`);
      continue;
    }

    if (choice === "gh-login") {
      const loginOk = await ghAuthLoginInteractive();
      if (!loginOk) continue;
      const token = ghCliToken();
      if (token && (await verifyTokenAccess(owner, repo, token))) {
        return { token, source: "gh-cli" };
      }
      warn(`gh is now logged in but doesn't have access to ${owner}/${repo}.`);
      continue;
    }

    if (choice === "gh-install-manual") {
      info(`See install instructions: ${kleur.underline("https://github.com/cli/cli#installation")}`);
      const cont = await confirm({
        message: "Come back once installed?",
        default: false,
      });
      if (!cont) return { token: null, source: "none" };
      continue;
    }

    if (choice === "paste") {
      const token = await pastePatInteractive(owner, repo);
      if (token) return { token, source: "pasted" };
      // fall back to menu; user can try another approach
      continue;
    }
  }
  return { token: null, source: "none" };
}


/** The paste-a-PAT sub-flow — separated so the menu can call it repeatedly. */
async function pastePatInteractive(owner: string, repo: string): Promise<string | null> {
  info(`Create a token: ${kleur.underline(patCreationUrl(owner, repo))}`);
  info(kleur.dim("The scopes 'repo' and 'read:org' are pre-selected in that URL."));
  tryOpenBrowser(patCreationUrl(owner, repo));

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const pasted = (
      await password({
        message:
          attempt === 0
            ? "Paste your PAT (or press Enter to try another method):"
            : `Attempt ${attempt + 1}/3 — that token didn't grant access. Try again:`,
        mask: "*",
      })
    ).trim();
    if (!pasted) return null; // bounce back to menu
    if (await verifyTokenAccess(owner, repo, pasted)) return pasted;
  }
  warn("3 PATs tried, none worked. Bouncing back to menu.");
  return null;
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

// ── gh CLI install + login detection ────────────────────────────────

export type GhState = "installed-and-logged-in" | "installed-not-logged-in" | "not-installed";

/** Detect whether `gh` is installed AND authenticated. */
export function detectGhState(): GhState {
  try {
    execFileSync("gh", ["--version"], {
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 2000,
    });
  } catch {
    return "not-installed";
  }
  try {
    execFileSync("gh", ["auth", "token"], {
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 2000,
    });
    return "installed-and-logged-in";
  } catch {
    return "installed-not-logged-in";
  }
}

/** Best-guess install command for the current OS + package manager.
 *  Returns null if we can't offer a one-liner. */
export function ghInstallCommand(): { label: string; cmd: string; args: string[] } | null {
  if (process.platform === "darwin") {
    if (hasCmd("brew")) {
      return { label: "brew install gh", cmd: "brew", args: ["install", "gh"] };
    }
  }
  if (process.platform === "linux") {
    if (hasCmd("apt-get")) {
      return {
        label: "sudo apt-get install -y gh",
        cmd: "sh",
        args: ["-c", "sudo apt-get update && sudo apt-get install -y gh"],
      };
    }
    if (hasCmd("dnf")) {
      return { label: "sudo dnf install -y gh", cmd: "sh", args: ["-c", "sudo dnf install -y gh"] };
    }
    if (hasCmd("pacman")) {
      return {
        label: "sudo pacman -S --noconfirm github-cli",
        cmd: "sh",
        args: ["-c", "sudo pacman -S --noconfirm github-cli"],
      };
    }
  }
  if (process.platform === "win32") {
    if (hasCmd("winget")) {
      return {
        label: "winget install --id GitHub.cli",
        cmd: "winget",
        args: ["install", "--id", "GitHub.cli"],
      };
    }
    if (hasCmd("choco")) {
      return { label: "choco install gh", cmd: "choco", args: ["install", "gh", "-y"] };
    }
  }
  return null;
}

function hasCmd(name: string): boolean {
  try {
    execFileSync(process.platform === "win32" ? "where" : "which", [name], {
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 1500,
    });
    return true;
  } catch {
    return false;
  }
}

/**
 * Run a shell command interactively (inherits our stdio so the user sees
 * it live). Returns exit code.
 */
async function runInteractive(cmd: string, args: string[]): Promise<number> {
  return new Promise((resolvePromise) => {
    const child = spawn(cmd, args, { stdio: "inherit" });
    child.on("close", (code) => resolvePromise(code ?? 1));
    child.on("error", () => resolvePromise(1));
  });
}

/** Attempt to install gh. Returns true on success. */
export async function installGhCli(): Promise<boolean> {
  const install = ghInstallCommand();
  if (!install) {
    warn(
      "I don't know how to install gh on this system automatically.",
      "See https://github.com/cli/cli#installation",
    );
    return false;
  }
  info(`Running: ${kleur.bold(install.label)}`);
  const code = await runInteractive(install.cmd, install.args);
  if (code === 0 && detectGhState() !== "not-installed") {
    ok("gh CLI installed");
    return true;
  }
  warn("gh install didn't complete cleanly.");
  return false;
}

/**
 * Run `gh auth login --web` interactively. This kicks off gh's own
 * device-code OAuth flow — user goes to github.com/login/device, enters
 * a code, authorizes, comes back. No PAT to paste.
 */
export async function ghAuthLoginInteractive(): Promise<boolean> {
  info("Starting: gh auth login --web  (opens your browser)");
  const code = await runInteractive("gh", [
    "auth",
    "login",
    "--web",
    "--git-protocol",
    "https",
    "--hostname",
    "github.com",
  ]);
  if (code === 0 && detectGhState() === "installed-and-logged-in") {
    ok("gh CLI authenticated");
    return true;
  }
  warn("gh auth login didn't complete.");
  return false;
}
