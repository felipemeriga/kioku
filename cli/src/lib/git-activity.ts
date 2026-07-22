import { execSync } from "node:child_process";

function git(cwd: string, args: string): string {
  return execSync(`git ${args}`, {
    cwd,
    stdio: ["ignore", "pipe", "ignore"],
    encoding: "utf8",
  }).trim();
}

function isRepo(cwd: string): boolean {
  try {
    git(cwd, "rev-parse --is-inside-work-tree");
    return true;
  } catch {
    return false;
  }
}

export interface Activity {
  branch: string;
  ahead: number;
  behind: number;
  commits: string[];
  working: string[];
}

export function gitActivity(
  cwd: string,
  opts: { sinceIso?: string; maxCommits?: number } = {},
): Activity {
  const branch = safe(cwd, "rev-parse --abbrev-ref HEAD") || "(detached)";
  let ahead = 0;
  let behind = 0;
  const counts = safe(cwd, "rev-list --left-right --count @{upstream}...HEAD");
  if (counts) {
    const [b, a] = counts.split(/\s+/).map((n) => parseInt(n, 10) || 0);
    behind = b;
    ahead = a;
  }
  const max = opts.maxCommits ?? 15;
  const range = opts.sinceIso
    ? `--since=${JSON.stringify(opts.sinceIso)}`
    : `-n ${max}`;
  const log = safe(cwd, `log ${range} "--pretty=format:%h · %ad · %s" --date=short`);
  const commits = log ? log.split("\n").slice(0, max) : [];
  const status = safe(cwd, "status --short");
  const working = status ? status.split("\n").filter(Boolean) : [];
  return { branch, ahead, behind, commits, working };
}

function safe(cwd: string, args: string): string {
  try {
    return git(cwd, args);
  } catch {
    return "";
  }
}

export function composeActivity(cwd: string, sinceIso?: string): string {
  if (!isRepo(cwd)) return "";
  const a = gitActivity(cwd, { sinceIso });
  const lines: string[] = ["## Recent changes (live from local clone)"];
  const track =
    a.ahead || a.behind ? ` (ahead ${a.ahead}, behind ${a.behind})` : "";
  lines.push(`Branch: ${a.branch}${track}`);
  if (a.commits.length) {
    lines.push("", "Recent commits:");
    for (const c of a.commits) lines.push(`  ${c}`);
  }
  if (a.working.length) {
    lines.push("", "Uncommitted working changes:");
    for (const w of a.working) lines.push(`  ${w}`);
  }
  return lines.join("\n");
}
