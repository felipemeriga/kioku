import { basename, resolve } from "node:path";
import { input, select, password, confirm } from "@inquirer/prompts";
import kleur from "kleur";
import {
  connectGitHub,
  createFolder,
  listChildren,
  mintScopedApiKey,
  updateFolder,
  whoami,
  type Folder,
} from "../lib/api.js";
import { isLoggedIn } from "../lib/config.js";
import { detectGit } from "../lib/git.js";
import {
  installSessionStartHook,
  updateClaudeMd,
  updateGitignore,
  writeMcpConfig,
} from "../lib/claude.js";
import { bad, box, info, ok, section, warn } from "../lib/banner.js";

interface InitOptions {
  yes?: boolean;
  root?: string;
  githubToken?: string;
}

export async function init(cwd: string, opts: InitOptions = {}): Promise<void> {
  const repoRoot = resolve(cwd);
  if (!isLoggedIn()) {
    warn("Not signed in yet.", "Run: agentic-rag login");
    process.exitCode = 1;
    return;
  }

  section("Wire this repo to agentic-rag");
  info(`Working directory: ${repoRoot}`);
  const git = detectGit(repoRoot);
  if (!git.isRepo) {
    bad("Not a git repo.", "Run `git init` first, or cd into one.");
    process.exitCode = 1;
    return;
  }
  info(
    git.remoteUrl
      ? `Detected remote: ${git.owner}/${git.repo}`
      : "No remote configured — GitHub sync will be skipped.",
  );

  // Step 1: pick a root folder
  const w = await whoami();
  if (w.root_folders.length === 0) {
    // First-time flow: no roots exist yet. Suggest the GitHub owner as
    // the root name (falling back to 'personal'), since that's usually
    // a company or username that groups multiple repos.
    const suggested = git.owner ?? "personal";
    info("You have no root folders yet. A root usually represents a company or a personal workspace.");
    const name = await input({
      message: "Name for your first root:",
      default: suggested,
    });
    const created = await createFolder(name.trim(), null);
    w.root_folders.push({
      id: created.id,
      name: created.name,
      kind: (created.kind as "folder" | "repo") ?? "folder",
      parent_id: null,
    });
  }
  let rootId: string | undefined;
  if (opts.root) {
    const hit = w.root_folders.find(
      (f) => f.name.toLowerCase() === opts.root!.toLowerCase() || f.id === opts.root,
    );
    if (!hit) {
      console.log(kleur.red(`No root folder named "${opts.root}"`));
      process.exitCode = 1;
      return;
    }
    rootId = hit.id;
  } else {
    rootId = await select({
      message: "Which root folder does this repo belong to?",
      choices: [
        ...w.root_folders.map((f) => ({ name: `${f.name}${f.kind === "repo" ? " (repo)" : ""}`, value: f.id })),
        { name: kleur.dim("+ create a new root"), value: "__create__" },
      ],
    });
    if (rootId === "__create__") {
      const name = await input({ message: "New root folder name:" });
      const created = await createFolder(name.trim(), null);
      rootId = created.id;
      w.root_folders.push({
        id: created.id, name: created.name,
        kind: "folder", parent_id: null,
      });
    }
  }

  // Step 2: pick a folder inside the chosen root to bind this repo to.
  //
  // Three affordances:
  //   a. Attach to an existing folder (turn it into a repo)
  //   b. Create a new folder for this repo
  //   c. Fast-path: an exact name match with the repo's basename +
  //      --yes flag → auto-attach without prompting.
  const desiredName = git.repo ?? basename(repoRoot);
  const children = await listChildren(rootId!);
  const nameMatch = children.find(
    (f) => f.name.toLowerCase() === desiredName.toLowerCase(),
  );

  let repoFolder: Folder;
  if (opts.yes && nameMatch) {
    repoFolder = nameMatch;
    info(`Attaching to existing folder "${repoFolder.name}"`);
  } else if (opts.yes && !nameMatch) {
    info(`Creating folder "${desiredName}"…`);
    repoFolder = await createFolder(desiredName, rootId!);
  } else {
    const choice = await select<string>({
      message: "Which folder does this repo bind to?",
      choices: [
        // Fast option — the auto-match, if any, on top with a hint.
        ...(nameMatch
          ? [{
              name: `${nameMatch.name}  ${kleur.dim("(matches your repo name — recommended)")}`,
              value: nameMatch.id,
            }]
          : []),
        // Other existing children — attach and mark as repo
        ...children
          .filter((f) => !nameMatch || f.id !== nameMatch.id)
          .map((f) => ({
            name: `${f.name}${f.kind === "repo" ? kleur.dim("  (already a repo)") : ""}`,
            value: f.id,
          })),
        { name: kleur.dim(`+ create new folder "${desiredName}"`), value: "__create__" },
        { name: kleur.dim("+ create new folder with different name"), value: "__create_named__" },
      ],
    });
    if (choice === "__create__") {
      info(`Creating folder "${desiredName}"…`);
      repoFolder = await createFolder(desiredName, rootId!);
    } else if (choice === "__create_named__") {
      const name = await input({
        message: "New folder name:",
        default: desiredName,
      });
      info(`Creating folder "${name}"…`);
      repoFolder = await createFolder(name.trim(), rootId!);
    } else {
      repoFolder = children.find((f) => f.id === choice)!;
      info(`Attaching to "${repoFolder.name}"`);
    }
  }

  // Step 2b: mark the folder as a repo (idempotent — no-ops if already
  // kind='repo'). GitHub connect below would also flip it, but doing it
  // here means the briefing works even if the user skips the token step
  // for a public repo, and it makes the intent explicit.
  if (repoFolder.kind !== "repo") {
    repoFolder = await updateFolder(repoFolder.id, { kind: "repo" });
    ok("Folder marked as repo");
  }

  // Step 3: GitHub connect (if we have a remote)
  if (git.owner && git.repo) {
    const yes = opts.yes || await confirm({
      message: `Sync this repo with GitHub (${git.owner}/${git.repo})?`,
      default: true,
    });
    if (yes) {
      const token = opts.githubToken ?? await password({
        message:
          "GitHub personal access token (leave empty for public repos):",
        mask: "*",
      });
      try {
        await connectGitHub({
          root_folder_id: repoFolder.id,
          repo_url: `${git.owner}/${git.repo}`,
          token: token || undefined,
          since_days: 30,
        });
        ok("GitHub sync configured");
      } catch (err) {
        warn(
          `GitHub sync couldn't be wired: ${err instanceof Error ? err.message : String(err)}`,
          "You can retry from the web UI.",
        );
      }
    }
  }

  // Step 4: mint an api key scoped to the ROOT (so Claude Code can drill
  // sibling repos in this workspace).
  info("Minting API key scoped to root…");
  const key = await mintScopedApiKey({
    scope_folder_id: rootId!,
    name: `cli-${desiredName}-${new Date().toISOString().slice(0, 10)}`,
  });
  ok(`API key created  ${kleur.dim(key.id.slice(0, 8) + "…")}`);

  // Step 5: write .mcp.json
  const mcpEntry = (key.mcp_config as {
    mcpServers: Record<string, { url: string; headers: Record<string, string> }>;
  }).mcpServers["agentic-rag"];
  const mcp = writeMcpConfig(repoRoot, mcpEntry);
  ok(`.mcp.json ${mcp.existed ? "updated" : "written"}`);

  // Step 6: SessionStart hook
  const hook = installSessionStartHook(repoRoot);
  ok(
    hook.addedHook
      ? "SessionStart hook installed"
      : "SessionStart hook already present",
  );

  // Step 7: CLAUDE.md
  const md = updateClaudeMd(repoRoot);
  ok(
    md.action === "created"
      ? "CLAUDE.md created"
      : md.action === "appended"
      ? "CLAUDE.md — second-brain instructions appended"
      : "CLAUDE.md — second-brain instructions updated",
  );

  // Step 8: .gitignore
  const gi = updateGitignore(repoRoot);
  if (gi.changed) {
    ok(".gitignore updated (secrets excluded)");
  }

  console.log();
  box([
    `${kleur.green("✓")} ${kleur.bold("This repo is now wired.")}`,
    kleur.dim(`  Scope: ${w.root_folders.find((f) => f.id === rootId)?.name ?? "(root)"}`),
    kleur.dim(`  Repo:  ${repoFolder.name}`),
    kleur.dim("  Open in Claude Code — the hook loads your briefing at session start."),
  ]);
  console.log();
}
