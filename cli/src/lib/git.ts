/**
 * Git remote introspection. Used during `init` to detect the repo the
 * CLI is being run against.
 */

import { execSync } from "node:child_process";

export interface GitInfo {
  isRepo: boolean;
  remoteUrl?: string;
  owner?: string;
  repo?: string;
}

export function detectGit(cwd: string = process.cwd()): GitInfo {
  try {
    execSync("git rev-parse --is-inside-work-tree", {
      cwd,
      stdio: "ignore",
    });
  } catch {
    return { isRepo: false };
  }
  let remoteUrl: string | undefined;
  try {
    remoteUrl = execSync("git config --get remote.origin.url", {
      cwd,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    // No origin — still a valid repo, just no remote to sync.
    return { isRepo: true };
  }
  const parsed = parseRemote(remoteUrl);
  return { isRepo: true, remoteUrl, ...parsed };
}

/** Current HEAD commit SHA, or undefined if not a repo / no commits yet. */
export function headSha(cwd: string = process.cwd()): string | undefined {
  try {
    return execSync("git rev-parse HEAD", {
      cwd,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    return undefined;
  }
}

/** Parse GitHub remotes in HTTPS or SSH form. */
export function parseRemote(remoteUrl: string): {
  owner?: string;
  repo?: string;
} {
  // git@github.com:owner/repo.git
  const ssh = /^git@github\.com:([^/]+)\/(.+?)(?:\.git)?$/.exec(remoteUrl);
  if (ssh) return { owner: ssh[1], repo: ssh[2] };
  // https://github.com/owner/repo(.git)
  const https = /^https?:\/\/github\.com\/([^/]+)\/(.+?)(?:\.git)?\/?$/.exec(
    remoteUrl
  );
  if (https) return { owner: https[1], repo: https[2] };
  return {};
}
