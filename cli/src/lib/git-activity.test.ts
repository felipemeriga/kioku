import { test } from "node:test";
import assert from "node:assert/strict";
import { execSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gitActivity, composeActivity } from "./git-activity.js";

function tempRepo(): string {
  const dir = mkdtempSync(join(tmpdir(), "kioku-git-"));
  const run = (c: string) => execSync(c, { cwd: dir, stdio: "ignore" });
  run("git init -q");
  run("git config user.email t@t.co");
  run("git config user.name t");
  writeFileSync(join(dir, "a.txt"), "1");
  run("git add a.txt");
  run("git commit -qm 'first commit'");
  return dir;
}

test("gitActivity reports branch, commits, and working changes", () => {
  const dir = tempRepo();
  writeFileSync(join(dir, "b.txt"), "wip"); // untracked working change
  const a = gitActivity(dir, { maxCommits: 10 });
  assert.ok(a.branch.length > 0);
  assert.ok(a.commits.some((c) => c.includes("first commit")));
  assert.ok(a.working.some((w) => w.includes("b.txt")));
});

test("composeActivity returns text with a Recent changes heading", () => {
  const dir = tempRepo();
  const out = composeActivity(dir);
  assert.match(out, /Recent changes/i);
  assert.match(out, /first commit/);
});

test("composeActivity is empty for a non-repo", () => {
  assert.equal(composeActivity(mkdtempSync(join(tmpdir(), "kioku-nonrepo-"))), "");
});
