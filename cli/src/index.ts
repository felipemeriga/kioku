#!/usr/bin/env node
import { Command } from "commander";
import kleur from "kleur";
import { capture } from "./commands/capture.js";
import { login } from "./commands/login.js";
import { init } from "./commands/init.js";
import { sessionStart } from "./commands/session-start.js";
import { status } from "./commands/status.js";
import { banner } from "./lib/banner.js";

const program = new Command();

program
  .name("agentic-rag")
  .description(
    "Wire a local repo to your agentic-rag second-brain — MCP, SessionStart hook, CLAUDE.md.",
  )
  .version("0.1.0");

program
  .command("login")
  .description("Sign in via email OTP")
  .action(async () => {
    banner();
    try {
      await login();
    } catch (err) {
      console.error(kleur.red("✗ ") + (err instanceof Error ? err.message : err));
      process.exitCode = 1;
    }
  });

program
  .command("init")
  .description("Wire the current repo — MCP, hook, CLAUDE.md, GitHub sync")
  .option("--root <name>", "Pre-select a root folder by name or id")
  .option("--yes", "Skip prompts where a sensible default exists")
  .option("--github-token <token>", "GitHub token (bypasses tier detection)")
  .option("--skip-github", "Skip GitHub sync — briefings won't include activity")
  .action(async (opts) => {
    banner();
    try {
      await init(process.cwd(), opts);
    } catch (err) {
      console.error(kleur.red("✗ ") + (err instanceof Error ? err.message : err));
      process.exitCode = 1;
    }
  });

program
  .command("session-start")
  .description("Fetch a compact briefing (used by the SessionStart hook)")
  .action(async () => {
    try {
      await sessionStart();
    } catch (err) {
      // never fail a hook — just be quiet
      if (process.env.AGENTIC_RAG_DEBUG) console.error(err);
    }
  });

program
  .command("capture")
  .description(
    "Distill session learnings and save to Mem0 (used by the Stop hook)",
  )
  .action(async () => {
    try {
      await capture();
    } catch (err) {
      // never fail a hook
      if (process.env.AGENTIC_RAG_DEBUG) console.error(err);
    }
  });

program
  .command("status")
  .description("Show login + repo binding status")
  .action(async () => {
    try {
      await status();
    } catch (err) {
      console.error(kleur.red("✗ ") + (err instanceof Error ? err.message : err));
      process.exitCode = 1;
    }
  });

program.parseAsync(process.argv);
