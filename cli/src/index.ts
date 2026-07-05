#!/usr/bin/env node
import { Command } from "commander";
import kleur from "kleur";
import { briefing } from "./commands/briefing.js";
import { capture } from "./commands/capture.js";
import { doctor } from "./commands/doctor.js";
import { init } from "./commands/init.js";
import { login } from "./commands/login.js";
import { logout } from "./commands/logout.js";
import { ls } from "./commands/ls.js";
import { openCmd } from "./commands/open.js";
import { quickstart } from "./commands/quickstart.js";
import { search } from "./commands/search.js";
import { sessionStart } from "./commands/session-start.js";
import { status } from "./commands/status.js";
import { welcome } from "./commands/welcome.js";
import { whoami } from "./commands/whoami.js";
import { banner, printError } from "./lib/banner.js";
import { checkForUpdate } from "./lib/update-check.js";

const VERSION = "0.1.0";

// Verbose --version — intercept before commander shows the plain number.
if (process.argv.includes("-V") || process.argv.includes("--version")) {
  const cfgPath =
    process.env.XDG_CONFIG_HOME
      ? `${process.env.XDG_CONFIG_HOME}/agentic-rag/config.json`
      : `${process.env.HOME}/.config/agentic-rag/config.json`;
  console.log(`agentic-rag  ${VERSION}`);
  console.log(`  node       ${process.version}`);
  console.log(`  platform   ${process.platform}-${process.arch}`);
  console.log(`  config     ${cfgPath}`);
  const apiBase = process.env.AGENTIC_RAG_API_BASE || "http://localhost:8000";
  console.log(`  api base   ${apiBase}`);
  process.exit(0);
}

const program = new Command();

program
  .name("agentic-rag")
  .description(
    "Wire a local repo to your agentic-rag second-brain — MCP, SessionStart hook, CLAUDE.md.",
  )
  .version(
    VERSION,
    "-V, --version",
    "Show version + runtime info",
  )
  // Global flags — read early so every command respects them.
  .option("--quiet", "Suppress banner and progress lines")
  .option("--no-color", "Disable ANSI colors (same as NO_COLOR=1)")
  .option("--api-base <url>", "Override AGENTIC_RAG_API_BASE for this invocation")
  .hook("preAction", (thisCommand) => {
    const opts = thisCommand.opts();
    if (opts.quiet) process.env.AGENTIC_RAG_QUIET = "1";
    if (opts.color === false) process.env.NO_COLOR = "1";
    if (opts.apiBase) process.env.AGENTIC_RAG_API_BASE = opts.apiBase;
  })
  .addHelpText(
    "after",
    `
Examples:
  $ agentic-rag login                      # sign in with email + OTP
  $ cd ~/repo && agentic-rag init          # wire the current repo
  $ agentic-rag ls                         # browse your workspace
  $ agentic-rag briefing                   # view this repo's briefing
  $ agentic-rag doctor                     # diagnose any issues

Environment:
  AGENTIC_RAG_API_BASE   Backend REST URL (default: http://localhost:8000)
  AGENTIC_RAG_MCP_URL    MCP SSE URL (default: derived from API base)
  AGENTIC_RAG_DEBUG      Verbose logging for hooks and errors
  NO_COLOR               Disable ANSI colors
  AGENTIC_RAG_QUIET      Suppress banner and progress lines

Docs: https://github.com/felipemeriga/agentic-rag/tree/main/cli
`,
  );

program
  .command("quickstart")
  .description("Sign in + wire the current repo in one guided flow")
  .option("--yes", "Skip prompts where a sensible default exists")
  .addHelpText(
    "after",
    `
Examples:
  $ cd ~/my-repo && agentic-rag quickstart
  $ agentic-rag quickstart --yes           # zero prompts, take all defaults
`,
  )
  .action(async (opts) => {
    banner();
    try {
      await quickstart(opts);
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("login")
  .description("Sign in via email OTP")
  .addHelpText(
    "after",
    `
Examples:
  $ agentic-rag login              # prompts for email + 6-digit code
  # At the code prompt you can type 'resend' or 'r' to send a new one.
`,
  )
  .action(async () => {
    banner();
    try {

      await login();
    } catch (err) {
      printError(err);
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
  .addHelpText(
    "after",
    `
Examples:
  $ agentic-rag init                              # interactive with smart defaults
  $ agentic-rag init --yes                        # no prompts, take all defaults
  $ agentic-rag init --root my-company            # pre-select root
  $ agentic-rag init --skip-github                # public-only briefing (no repo sync)
  $ GH_TOKEN=ghp_... agentic-rag init             # env-var token

GitHub auth is auto-detected — no prompts unless nothing else works:
  1. --github-token flag
  2. gh CLI (\`gh auth token\`)
  3. GITHUB_TOKEN / GH_TOKEN env var
  4. Interactive menu (offer to install gh, run gh auth login, or paste a PAT)
`,
  )
  .action(async (opts) => {
    banner();
    try {
      await init(process.cwd(), opts);
    } catch (err) {
      printError(err);
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
  .command("doctor")
  .description("Run health checks — backend, MCP, session, per-repo files")
  .action(async () => {
    banner();
    try {
      await doctor();
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("logout")
  .description("Sign out — clears local tokens")
  .action(async () => {
    banner();
    try {
      await logout();
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("ls [path]")
  .description("Browse your workspace — list roots, or list a folder's children")
  .option("--json", "Machine-readable JSON output")
  .addHelpText(
    "after",
    `
Examples:
  $ agentic-rag ls                # list root folders
  $ agentic-rag ls personal       # list children of the 'personal' root
  $ agentic-rag ls cosm/c360-lead # deep path
  $ agentic-rag ls --json         # JSON for scripting
`,
  )
  .action(async (path, opts) => {
    if (!opts.json) banner();
    try {
      await ls(path, opts);
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("briefing")
  .description("View this repo's briefing — the same content Claude sees at session start")
  .option("--section <name>", "Show only one section")
  .option("--json", "Machine-readable JSON output")
  .addHelpText(
    "after",
    `
Examples:
  $ agentic-rag briefing                          # full 8-section briefing
  $ agentic-rag briefing --section deployment     # just one section
  $ agentic-rag briefing --json | jq .sections.overview
`,
  )
  .action(async (opts) => {
    if (!opts.json) banner();
    try {
      await briefing(opts);
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("whoami")
  .description("Print the signed-in email + user id")
  .option("--json", "Machine-readable JSON output")
  .action(async (opts) => {
    try {
      await whoami(opts);
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("open [target]")
  .description("Open the web UI in a browser — this repo's folder if wired")
  .option("--json", "Print the URL instead of opening")
  .addHelpText(
    "after",
    `
Examples:
  $ agentic-rag open                    # opens the current repo's folder
  $ agentic-rag open personal           # opens the 'personal' root by id/name
  $ agentic-rag open --json | jq -r .url
`,
  )
  .action(async (target, opts) => {
    if (!opts.json) banner();
    try {
      await openCmd(target, opts);
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("search <query...>")
  .description(
    "Search the knowledge base + memory — same tool Claude Code uses",
  )
  .option("--json", "Machine-readable JSON output")
  .option("--limit <n>", "How many hits to return (1-25, default 5)")
  .option("--folder <name>", "Narrow to a specific folder inside your scope")
  .addHelpText(
    "after",
    `
Examples:
  $ agentic-rag search how does deploy work
  $ agentic-rag search --limit 10 mem0 filter grammar
  $ agentic-rag search --json 'ruff format' | jq '.hits[0]'
`,
  )
  .action(async (queryParts, opts) => {
    if (!opts.json) banner();
    try {
      await search(queryParts.join(" "), opts);
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

program
  .command("status")
  .description("Show login + repo binding status")
  .action(async () => {
    try {
      await status();
    } catch (err) {
      printError(err);
      process.exitCode = 1;
    }
  });

// Bare `agentic-rag` (no subcommand) → smart welcome instead of --help.
// Users don't want to read a full command list to know what to do next.
if (process.argv.length <= 2) {
  banner();
  welcome()
    .then(() => checkForUpdate(VERSION))
    .catch((err) => {
      printError(err);
      process.exitCode = 1;
    });
} else {
  program.parseAsync(process.argv).then(() => {
    // Fire-and-forget update check AFTER the main command finishes so
    // we don't add latency to hot-path commands.
    void checkForUpdate(VERSION);
  });
}
