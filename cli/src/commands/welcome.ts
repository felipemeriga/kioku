/**
 * Bare `agentic-rag` — smart contextual welcome.
 *
 * Detects state + shows the SINGLE most useful next step. No walls of
 * text. Meant to answer "what do I do next?" in one glance.
 *
 * State flowchart:
 *   Not signed in           → "Run: agentic-rag login"
 *   Signed in, not in repo  → "Run this in a git repo, then: agentic-rag init"
 *   In repo, not wired      → "Run: agentic-rag init"
 *   In wired repo           → summary card + tips
 */

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import kleur from "kleur";
import { readConfig, isLoggedIn } from "../lib/config.js";
import { whoami as whoamiApi } from "../lib/api.js";
import { detectGit } from "../lib/git.js";
import { box, info, section } from "../lib/banner.js";

export async function welcome(): Promise<void> {
  const cfg = readConfig();

  // 1. Not signed in — one-line CTA
  if (!isLoggedIn()) {
    section("Welcome");
    info("Sign in to get started:");
    console.log(`    ${kleur.bold("agentic-rag login")}`);
    console.log();
    return;
  }

  const repoRoot = resolve(process.cwd());
  const git = detectGit(repoRoot);
  const statePath = join(repoRoot, ".claude", "agentic-rag-state.json");
  const wired = existsSync(statePath);

  // 2. Not in a git repo
  if (!git.isRepo) {
    section(`Hi ${cfg.email}`);
    info("You're not in a git repo yet. cd into one and run:");
    console.log(`    ${kleur.bold("agentic-rag init")}`);
    console.log();
    info("Or browse your workspace: " + kleur.bold("agentic-rag ls"));
    console.log();
    return;
  }

  // 3. In a git repo, not wired
  if (!wired) {
    section(`Hi ${cfg.email}`);
    info(
      git.owner
        ? `Detected ${git.owner}/${git.repo} — not wired to agentic-rag yet.`
        : "Detected a git repo — not wired to agentic-rag yet.",
    );
    console.log(`    ${kleur.bold("agentic-rag init")}    ${kleur.dim("# wire this repo")}`);
    console.log();
    return;
  }

  // 4. Wired repo — show a summary + suggestions
  const state = JSON.parse(readFileSync(statePath, "utf8")) as {
    folder_name?: string;
    scope_root_name?: string;
    last_capture_at?: string;
    last_capture_transcript_length?: number;
  };
  const lastCapture = state.last_capture_at
    ? formatRelative(new Date(state.last_capture_at))
    : "no captures yet";
  let roots = 0;
  try {
    const w = await whoamiApi();
    roots = w.root_folders.length;
  } catch {
    // Ignore — welcome shouldn't fail on API issues.
  }
  box([
    `${kleur.green("●")} ${kleur.bold("This repo is wired.")}`,
    kleur.dim(`  Repo:      ${state.folder_name ?? "(unknown)"}`),
    kleur.dim(`  Scope:     ${state.scope_root_name ?? "(unknown)"}`),
    kleur.dim(`  Last save: ${lastCapture}`),
    kleur.dim(`  Roots:     ${roots}`),
  ]);
  console.log();
  console.log(kleur.bold("  Handy commands:"));
  console.log(
    `    ${kleur.bold("agentic-rag briefing")}    ${kleur.dim("# view this repo's briefing")}`,
  );
  console.log(
    `    ${kleur.bold("agentic-rag ls")}          ${kleur.dim("# browse your workspace")}`,
  );
  console.log(
    `    ${kleur.bold("agentic-rag search \"...\"")}  ${kleur.dim("# knowledge base search")}`,
  );
  console.log(
    `    ${kleur.bold("agentic-rag open")}        ${kleur.dim("# open in web UI")}`,
  );
  console.log(
    `    ${kleur.bold("agentic-rag doctor")}      ${kleur.dim("# health checks")}`,
  );
  console.log();
}

function formatRelative(d: Date): string {
  const s = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  return `${days}d ago`;
}
