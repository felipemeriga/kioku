import { basename, resolve } from "node:path";
import { input, select, confirm } from "@inquirer/prompts";
import kleur from "kleur";
import {
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
  installStopHook,
  updateClaudeMd,
  updateGitignore,
  writeCaptureState,
  writeMcpConfig,
} from "../lib/claude.js";
import { bad, info, ok, section, step, warn } from "../lib/banner.js";
import { panel } from "../ui/panel.js";

interface InitOptions {
  yes?: boolean;
  root?: string;
}

export async function init(cwd: string, opts: InitOptions = {}): Promise<void> {
  const repoRoot = resolve(cwd);
  if (!isLoggedIn()) {
    warn("Not signed in yet.", "Run: kioku login");
    process.exitCode = 1;
    return;
  }

  section("Wire this repo to kioku");
  info(`Working directory: ${repoRoot}`);
  const git = detectGit(repoRoot);
  if (!git.isRepo) {
    bad("kioku init must be run inside a cloned git repository.",
        "cd into your repo's working copy and re-run.");
    process.exitCode = 1;
    return;
  }
  info(
    git.remoteUrl
      ? `Detected remote: ${git.owner}/${git.repo}`
      : "No remote configured.",
  );

  // Step 1: pick a root folder.
  //
  // Smart-default ladder — take the shortest path that doesn't ask a
  // question the user can't obviously answer:
  //   1. --root flag → use it (fail if missing)
  //   2. Only 1 root exists → use it silently
  //   3. A root name matches the GitHub owner → use it silently (this
  //      is the common case: 'personal' repo owner, 'personal' root)
  //   4. Nothing exists yet → auto-create a root named after the
  //      GitHub owner (or 'personal') and skip the prompt with --yes
  //   5. Otherwise → prompt with all the existing roots
  const w = await whoami();
  let rootId: string | undefined;

  if (opts.root) {
    const hit = w.root_folders.find(
      (f) => f.name.toLowerCase() === opts.root!.toLowerCase() || f.id === opts.root,
    );
    if (!hit) {
      throw new Error(
        `No root folder named "${opts.root}". Run without --root to pick from the list.`,
      );
    }
    rootId = hit.id;
    info(`Using root "${hit.name}"`);
  } else if (w.root_folders.length === 0) {
    // First-time flow — auto-name after the git owner.
    const name = (git.owner ?? "personal").trim();
    if (opts.yes) {
      const created = await createFolder(name, null);
      rootId = created.id;
      w.root_folders.push({
        id: created.id, name: created.name,
        kind: (created.kind as "folder" | "repo") ?? "folder",
        parent_id: null,
      });
      info(`Created your first root: "${name}"`);
    } else {
      const chosenName = await input({
        message: "Name for your first root:",
        default: name,
      });
      const created = await createFolder(chosenName.trim(), null);
      rootId = created.id;
      w.root_folders.push({
        id: created.id, name: created.name,
        kind: (created.kind as "folder" | "repo") ?? "folder",
        parent_id: null,
      });
    }
  } else if (w.root_folders.length === 1) {
    rootId = w.root_folders[0].id;
    info(`Using your only root "${w.root_folders[0].name}"`);
  } else {
    // Multiple roots — try to auto-pick if the git owner matches one.
    const ownerLower = git.owner?.toLowerCase();
    const ownerMatch = ownerLower
      ? w.root_folders.find((f) => f.name.toLowerCase() === ownerLower)
      : undefined;
    if (ownerMatch && opts.yes) {
      rootId = ownerMatch.id;
      info(`Using root "${ownerMatch.name}" (matches your GitHub owner)`);
    } else {
      rootId = await select<string>({
        message: "Which root does this repo belong to?",
        default: ownerMatch?.id,
        choices: [
          ...w.root_folders.map((f) => ({
            name:
              (ownerMatch && f.id === ownerMatch.id
                ? `${f.name}  ${kleur.dim("(matches your GitHub owner)")}`
                : f.name) +
              (f.kind === "repo" ? kleur.dim(" (repo)") : ""),
            value: f.id,
          })),
          { name: kleur.dim("+ create a new root"), value: "__create__" },
        ],
      });
      if (rootId === "__create__") {
        const name = await input({
          message: "New root folder name:",
          default: git.owner ?? "personal",
        });
        const created = await createFolder(name.trim(), null);
        rootId = created.id;
        w.root_folders.push({
          id: created.id, name: created.name,
          kind: "folder", parent_id: null,
        });
      }
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
  if (nameMatch && opts.yes) {
    // Non-interactive only: with --yes we silent-attach to the name match.
    // Interactively we always fall through to the picker so the user can
    // choose to reuse the existing folder or create a new one.
    repoFolder = nameMatch;
    info(
      `Attaching to existing ${nameMatch.kind === "repo" ? "repo" : "folder"} "${repoFolder.name}"`,
    );
  } else if (opts.yes && !nameMatch) {
    info(`Creating folder "${desiredName}"…`);
    repoFolder = await createFolder(desiredName, rootId!);
  } else if (!nameMatch && children.length === 0) {
    // Empty root — obvious answer: create the folder now, no picker.
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

  // Step 4: mint an api key scoped to the ROOT (so Claude Code can drill
  // sibling repos in this workspace).
  const key = await step("Minting API key", () =>
    mintScopedApiKey({
      scope_folder_id: rootId!,
      name: `cli-${desiredName}-${new Date().toISOString().slice(0, 10)}`,
    }),
  );

  // Step 5: write .mcp.json
  const mcpEntry = (key.mcp_config as {
    mcpServers: Record<string, { url: string; headers: Record<string, string> }>;
  }).mcpServers["kioku"];
  const mcp = writeMcpConfig(repoRoot, mcpEntry);
  ok(`.mcp.json ${mcp.existed ? "updated" : "written"}`);

  // Step 6a: SessionStart hook — fetches briefing at session start
  const hook = installSessionStartHook(repoRoot);
  ok(
    hook.addedHook
      ? "SessionStart hook installed"
      : "SessionStart hook already present",
  );

  // Step 6b: Stop hook — captures session learnings to Mem0 every 10 min
  //          or every 5 assistant turns.
  const stop = installStopHook(repoRoot);
  ok(
    stop.addedHook
      ? "Stop hook installed  " + kleur.dim("(captures learnings to Mem0)")
      : "Stop hook already present",
  );

  // Step 6c: state file the Stop hook uses to know which folder to save to
  //          and how much of the transcript has been captured already.
  const rootName = w.root_folders.find((f) => f.id === rootId)?.name ?? "(root)";
  writeCaptureState(repoRoot, {
    folder_id: repoFolder.id,
    folder_name: repoFolder.name,
    scope_root_name: rootName,
  });

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
  console.log(panel({
    title: "Repo wired",
    body: [
      `${kleur.green("✓")} ${kleur.bold("This repo is now wired.")}`,
      kleur.dim(`  Scope: ${w.root_folders.find((f) => f.id === rootId)?.name ?? "(root)"}`),
      kleur.dim(`  Repo:  ${repoFolder.name}`),
      kleur.dim("  Open in Claude Code — the hook loads your briefing at session start."),
    ].join("\n"),
    tone: "success",
  }));
  console.log();
}
