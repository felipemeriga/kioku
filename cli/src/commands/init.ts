import { basename, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { input, select, confirm } from "@inquirer/prompts";
import kleur from "kleur";
import {
  connectGitHub,
  createFolder,
  finalizeGithubClone,
  listChildren,
  mintScopedApiKey,
  prepareGithubClone,
  updateFolder,
  whoami,
  type Folder,
} from "../lib/api.js";
import { isLoggedIn } from "../lib/config.js";
import { detectGit } from "../lib/git.js";
import { detectRepoVisibility } from "../lib/github-auth.js";
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
  githubToken?: string;
  skipGithub?: boolean;
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
    bad("Not a git repo.", "Run `git init` first, or cd into one.");
    process.exitCode = 1;
    return;
  }
  info(
    git.remoteUrl
      ? `Detected remote: ${git.owner}/${git.repo}`
      : "No remote configured — GitHub sync will be skipped.",
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
  if (nameMatch && (opts.yes || nameMatch.kind === "repo")) {
    // Silent attach when either --yes is set OR the match is already a
    // repo (there's no other reasonable interpretation than 'reuse it').
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

  // Step 3: GitHub connect (if we have a remote).
  //
  // Two paths:
  //   - PUBLIC repo → backend clones via HTTPS, no auth needed.
  //   - PRIVATE/org repo → deploy key flow:
  //       1. backend generates Ed25519 keypair, returns public
  //       2. CLI adds public key via `gh repo deploy-key add`
  //       3. backend attempts SSH clone with the private key
  //
  // PATs are no longer stored server-side — token flag is accepted for
  // backward compat but the backend downgrades it to a public clone.
  if (git.owner && git.repo && !opts.skipGithub) {
    const shouldWire = opts.yes || await confirm({
      message: `Sync this repo with GitHub (${git.owner}/${git.repo})?`,
      default: true,
    });
    if (shouldWire) {
      const vis = await detectRepoVisibility(git.owner, git.repo);
      try {
        if (vis.visibility === "public") {
          info(`${git.owner}/${git.repo} is public — cloning via HTTPS.`);
          await step("Connecting to GitHub (public)", () =>
            connectGitHub({
              root_folder_id: repoFolder.id,
              repo_url: `${git.owner}/${git.repo}`,
              since_days: 30,
            }),
          );
          ok("GitHub sync configured via public clone");
        } else {
          // Private/unknown → deploy key flow. Requires local `gh` auth.
          await connectViaDeployKey(git.owner, git.repo, repoFolder.id, !!opts.yes);
        }
      } catch (err) {
        warn(
          `GitHub sync couldn't be wired: ${err instanceof Error ? err.message : String(err)}`,
          "Retry with: kioku init --yes  (or open the web UI for a public repo).",
        );
      }
    }
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


/**
 * Deploy-key connect flow for private/org repos.
 *
 *   1. POST /api/github/prepare-clone → backend generates Ed25519 keypair,
 *      stores private encrypted, returns public.
 *   2. CLI adds the public key via `gh repo deploy-key add`. If `gh` isn't
 *      authenticated or the org restricts deploy-key writes, we fall back
 *      to printing manual instructions.
 *   3. POST /api/github/finalize-clone → backend attempts SSH clone with
 *      the stored private key. On failure the config keeps the keypair
 *      so the user can retry after fixing whatever went wrong.
 *
 * Why deploy keys over PATs / GitHub Apps: read-only, per-repo, don't
 * expire, and rarely blocked by org policies that force 1-day PATs.
 */
async function connectViaDeployKey(
  owner: string,
  repo: string,
  folderId: string,
  nonInteractive: boolean,
): Promise<void> {
  info(`${owner}/${repo} appears private — setting up a deploy key.`);

  const prep = await step("Generating deploy keypair", () =>
    prepareGithubClone({
      root_folder_id: folderId,
      repo_url: `${owner}/${repo}`,
      since_days: 30,
    }),
  );

  // Try to install the public key automatically via gh. If gh isn't
  // available or the API call fails (e.g. no admin rights on the repo),
  // fall through to printing manual instructions.
  let installed = false;
  try {
    execFileSync(
      "gh",
      [
        "repo",
        "deploy-key",
        "add",
        "-",
        "--repo",
        `${owner}/${repo}`,
        "--title",
        "Kioku sync (read-only)",
      ],
      { input: prep.public_key, stdio: ["pipe", "pipe", "pipe"], timeout: 15000 },
    );
    installed = true;
    ok("Deploy key installed via gh CLI");
  } catch (err) {
    warn(
      `Couldn't auto-install deploy key: ${err instanceof Error ? err.message : String(err)}`,
    );
    console.log();
    console.log(kleur.dim("  Add it manually:"));
    console.log(kleur.dim(`    1. https://github.com/${owner}/${repo}/settings/keys`));
    console.log(kleur.dim("    2. Add deploy key with title 'Kioku sync (read-only)'"));
    console.log(kleur.dim("    3. Paste this public key:"));
    console.log();
    console.log("    " + prep.public_key);
    console.log();
    if (!nonInteractive) {
      await confirm({
        message: "Press enter when the key is installed to continue",
        default: true,
      });
      installed = true;
    }
  }

  if (!installed) {
    warn(
      "Skipping clone attempt — install the deploy key and rerun `kioku init --yes` to finish.",
    );
    return;
  }

  await step("Cloning via deploy key", () =>
    finalizeGithubClone({ config_id: prep.config_id }),
  );
  ok("GitHub sync configured via deploy key");
}
