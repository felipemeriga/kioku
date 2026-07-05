/**
 * `agentic-rag quickstart` — first-run flow.
 *
 * Combines login + init in one guided command so new users get from
 * zero to Claude Code in ~30 seconds. Skips login step if already
 * signed in.
 */

import kleur from "kleur";
import { detectGit } from "../lib/git.js";
import { isLoggedIn } from "../lib/config.js";
import { login } from "./login.js";
import { init } from "./init.js";
import { section, info, box } from "../lib/banner.js";

interface Opts {
  yes?: boolean;
}

export async function quickstart(opts: Opts): Promise<void> {
  const git = detectGit(process.cwd());
  if (!git.isRepo) {
    section("Quickstart");
    info("This command wires the CURRENT directory to agentic-rag. Run it inside a git repo.");
    info(`git init && git remote add origin <url> && agentic-rag quickstart`);
    process.exitCode = 1;
    return;
  }

  section("Quickstart");
  if (isLoggedIn()) {
    info("Already signed in. Wiring this repo now.");
  } else {
    info("First step: sign in. Second step: wire this repo.");
    console.log();
    await login();
  }
  console.log();
  await init(process.cwd(), { yes: opts.yes });
  console.log();
  box([
    `${kleur.green("✓")} ${kleur.bold("You're set.")}`,
    kleur.dim("  Open this repo in Claude Code — briefing loads at session start."),
    kleur.dim("  Try:  agentic-rag briefing   to see what Claude Code will see."),
  ]);
  console.log();
}
