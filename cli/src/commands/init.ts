import { basename, resolve } from "node:path";
import { confirm, input, select } from "@inquirer/prompts";
import kleur from "kleur";
import {
  ApiError,
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
  readMcpEntry,
  readRepoState,
  updateClaudeMd,
  updateGitignore,
  writeCaptureState,
  writeMcpConfig,
} from "../lib/claude.js";
import { bad, info, ok, section, step, warn } from "../lib/banner.js";
import { panel } from "../ui/panel.js";
import { generateInstruction } from "./session-start.js";
import { openCmd } from "./open.js";

interface InitOptions {
  yes?: boolean;
  root?: string;
  force?: boolean;
}

/** Reuse an existing scoped api key if it was minted within this window,
 *  instead of rotating it on every init. */
const RECENT_KEY_WINDOW_MS = 1000 * 60 * 60 * 24; // 24h

/** Compact "2h ago" style relative time for the last-generated hint. */
function relTime(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Create a folder, but tolerate a concurrent creator. Two `kioku init` runs
 *  (or a race with the UI) can both pass the listChildren check and then race
 *  on createFolder; the backend's unique-name constraint makes the loser get a
 *  409. Treat that as "attach to the folder the winner just created" instead of
 *  aborting init. */
async function createOrAttach(name: string, parentId: string): Promise<Folder> {
  try {
    return await createFolder(name, parentId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 409) {
      const siblings = await listChildren(parentId);
      const hit = siblings.find(
        (f) => f.name.toLowerCase() === name.toLowerCase()
      );
      if (hit) return hit;
    }
    throw err;
  }
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
    bad(
      "kioku init must be run inside a cloned git repository.",
      "cd into your repo's working copy and re-run."
    );
    process.exitCode = 1;
    return;
  }
  info(
    git.remoteUrl
      ? `Detected remote: ${git.owner}/${git.repo}`
      : "No remote configured."
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
      (f) =>
        f.name.toLowerCase() === opts.root!.toLowerCase() || f.id === opts.root
    );
    if (!hit) {
      throw new Error(
        `No root folder named "${opts.root}". Run without --root to pick from the list.`
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
        id: created.id,
        name: created.name,
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
        id: created.id,
        name: created.name,
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
    if (opts.yes) {
      // --yes must never block on a prompt: prefer the owner match, else the
      // first root. Use --root to pick a specific one non-interactively.
      const pick = ownerMatch ?? w.root_folders[0];
      rootId = pick.id;
      info(
        ownerMatch
          ? `Using root "${pick.name}" (matches your GitHub owner)`
          : `Using root "${pick.name}" (default — pass --root to choose another)`
      );
    } else {
      rootId = await select<string>({
        message: "Which root does this repo belong to?",
        default: ownerMatch?.id,
        choices: [
          ...w.root_folders.map((f) => ({
            name:
              (ownerMatch && f.id === ownerMatch.id
                ? `${f.name}  ${kleur.dim("(matches your GitHub owner)")}`
                : f.name) + (f.kind === "repo" ? kleur.dim(" (repo)") : ""),
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
          id: created.id,
          name: created.name,
          kind: "folder",
          parent_id: null,
        });
      }
    }
  }

  // Step 2: bind this repo to <root>/repositories/<repo-name>.
  //
  // Convention over configuration: every repo lives under a "repositories"
  // container in its root, named after the git repo — no renaming, no picker.
  // This keeps the workspace predictable (shared docs that sit ABOVE
  // repositories/ flow into every repo's briefing) and identical across
  // machines. If the repo folder already exists we attach to it.
  const rootName =
    w.root_folders.find((f) => f.id === rootId)?.name ?? "(root)";
  const desiredName = git.repo ?? basename(repoRoot);
  const reposContainer = await createOrAttach("repositories", rootId!);
  const siblings = await listChildren(reposContainer.id);
  const existing = siblings.find(
    (f) => f.name.toLowerCase() === desiredName.toLowerCase()
  );

  let repoFolder: Folder;
  if (existing) {
    repoFolder = existing;
    info(
      `Attaching to existing ${
        existing.kind === "repo" ? "repo" : "folder"
      } "${rootName}/repositories/${desiredName}"`
    );
  } else {
    info(`Creating "${rootName}/repositories/${desiredName}"…`);
    repoFolder = await createOrAttach(desiredName, reposContainer.id);
  }

  // Step 2b: mark the folder as a repo (idempotent — no-ops if already
  // kind='repo'). GitHub connect below would also flip it, but doing it
  // here means the briefing works even if the user skips the token step
  // for a public repo, and it makes the intent explicit.
  if (repoFolder.kind !== "repo") {
    repoFolder = await updateFolder(repoFolder.id, { kind: "repo" });
    ok("Folder marked as repo");
  }

  // Step 4: mint an api key scoped to THIS REPO's folder (not the root).
  //
  // The api_keys table has a unique constraint on (user_id, scope_folder_id)
  // and minting deletes any prior key for the same scope. If we scoped to the
  // root, every repo under that root would share one scope — so initializing a
  // second repo would revoke the first repo's key, silently breaking its
  // .mcp.json (401). Scoping per-repo gives each repo its own key that survives
  // sibling inits; re-initializing the same repo cleanly rotates only its own
  // key. (Cross-repo drilling via a single root-scoped key is a v2 concern.)
  // Reuse a recently-minted key for THIS repo instead of rotating it on every
  // init. The plaintext key already lives in .mcp.json; minting deletes the old
  // key, so a needless re-mint churns it (and can 401 other machines still
  // holding the previous one). Only re-mint when there's no recent local key.
  const priorState = readRepoState(repoRoot);
  const priorMcp = readMcpEntry(repoRoot);
  const priorMintedAt = priorState?.api_key_minted_at
    ? Date.parse(priorState.api_key_minted_at)
    : NaN;
  const canReuseKey =
    priorState?.folder_id === repoFolder.id &&
    !!priorMcp?.key &&
    !Number.isNaN(priorMintedAt) &&
    Date.now() - priorMintedAt < RECENT_KEY_WINDOW_MS;

  let key: { key: string; mcp_config: unknown };
  let keyMintedAt: string;
  if (canReuseKey && priorState?.api_key_minted_at) {
    key = {
      key: priorMcp!.key,
      mcp_config: { mcpServers: { kioku: priorMcp!.entry } },
    };
    keyMintedAt = priorState.api_key_minted_at;
    ok(`Reusing API key minted ${relTime(keyMintedAt)}`);
  } else {
    key = await step("Minting API key", () =>
      mintScopedApiKey({
        scope_folder_id: repoFolder.id,
        name: `cli-${desiredName}-${new Date().toISOString().slice(0, 10)}`,
      })
    );
    keyMintedAt = new Date().toISOString();
  }

  // Step 5: write .mcp.json
  const mcpEntry = (
    key.mcp_config as {
      mcpServers: Record<
        string,
        { url: string; headers: Record<string, string> }
      >;
    }
  ).mcpServers["kioku"];
  const mcp = writeMcpConfig(repoRoot, mcpEntry);
  ok(`.mcp.json ${mcp.existed ? "updated" : "written"}`);

  // Step 6a: SessionStart hook — fetches briefing at session start
  const hook = installSessionStartHook(repoRoot);
  ok(
    hook.addedHook
      ? "SessionStart hook installed"
      : "SessionStart hook already present"
  );

  // Step 6b: Stop hook — captures session learnings to Mem0 every 10 min
  //          or every 5 assistant turns.
  const stop = installStopHook(repoRoot);
  ok(
    stop.addedHook
      ? "Stop hook installed  " + kleur.dim("(captures learnings to Mem0)")
      : "Stop hook already present"
  );

  // Step 6c: state file the Stop hook uses to know which folder to save to
  //          and how much of the transcript has been captured already.
  writeCaptureState(repoRoot, {
    folder_id: repoFolder.id,
    folder_name: repoFolder.name,
    scope_root_name: rootName,
    api_key_minted_at: keyMintedAt,
  });

  // Step 7: CLAUDE.md
  const md = updateClaudeMd(repoRoot);
  ok(
    md.action === "created"
      ? "CLAUDE.md created"
      : md.action === "appended"
      ? "CLAUDE.md — second-brain instructions appended"
      : "CLAUDE.md — second-brain instructions updated"
  );

  // Step 8: .gitignore
  const gi = updateGitignore(repoRoot);
  if (gi.changed) {
    ok(".gitignore updated (secrets excluded)");
  }

  console.log();
  console.log(
    panel({
      title: "Repo wired",
      body: [
        `${kleur.green("✓")} ${kleur.bold("This repo is now wired.")}`,
        kleur.dim(
          `  Scope: ${
            w.root_folders.find((f) => f.id === rootId)?.name ?? "(root)"
          }`
        ),
        kleur.dim(`  Repo:  ${repoFolder.name}`),
      ].join("\n"),
      tone: "success",
    })
  );
  console.log();

  // Step 9: generate the briefing NOW by opening Claude Code here with the
  // generation as its first task. The user waits once while it scans the repo
  // (briefing + activity + the detailed doc), then keeps coding in a session
  // that already has the summary. No detached background process — it adds no
  // value for this very first session, which is exactly when you want the
  // briefing ready.
  try {
    const restBase = new URL(mcpEntry.url).origin.replace(/:8001$/, ":8000");
    const res = await fetch(
      `${restBase}/api/cli/folder-summary?folder_id=${encodeURIComponent(
        repoFolder.id
      )}`,
      { headers: { Authorization: `Bearer ${key.key}` } }
    );
    const summary = res.ok
      ? ((await res.json()) as {
          needs_generation?: boolean;
          generated_at?: string | null;
          section_order?: string[];
          doc_count?: number;
          has_notion?: boolean;
        })
      : null;

    const isTTY = process.stdin.isTTY && process.stdout.isTTY;
    // A briefing "exists" if it has ever been generated (regardless of
    // staleness). Key on generated_at, not needs_generation, so a repo that
    // already has a briefing prompts to regenerate instead of silently
    // skipping (or silently regenerating once it goes stale).
    const hasBriefing = Boolean(summary?.generated_at);

    let shouldGenerate = false;
    if (summary) {
      if (!hasBriefing) {
        // No briefing yet — generate it as the session's first task. Only in an
        // interactive terminal (we launch Claude Code with stdio inherited).
        shouldGenerate = isTTY;
      } else if (opts.force) {
        shouldGenerate = true;
      } else if (isTTY && !opts.yes) {
        // Briefing already exists — ask before spending tokens regenerating.
        shouldGenerate = await confirm({
          message: `This repo already has a briefing (generated ${relTime(
            summary.generated_at!
          )}). Regenerate it?`,
          default: false,
        });
        if (!shouldGenerate) {
          info(
            "Keeping the existing briefing. Re-run with --force to regenerate."
          );
        }
      }
      // Existing briefing under --yes / non-TTY without --force: skip quietly.
    }

    // Educate: a folder seeded with docs / Notion produces a much richer
    // briefing (Claude folds them in via read_folder_documents). Base this on
    // ACTUAL synced docs, not just a Notion config — a just-connected Notion
    // hasn't synced yet, so its pages aren't in the folder to fold in.
    const hasDocs = (summary?.doc_count ?? 0) > 0;
    if (summary && !hasDocs && isTTY) {
      if (summary.has_notion) {
        info(
          "💡 Notion is connected but no documents have synced to this folder yet."
        );
        info(
          "   Wait for the sync to finish (or click Sync now in the web UI), then"
        );
        info(
          "   re-run kioku init --force so the briefing includes your Notion content."
        );
      } else {
        info(
          "💡 Seed this folder for a richer briefing — one that understands your whole"
        );
        info(
          "   ecosystem, not just the code: add docs or connect Notion in the web UI,"
        );
        info("   then re-run with kioku init --force.");
      }
      if (shouldGenerate && !opts.yes && !opts.force) {
        const openFirst = await confirm({
          message: summary.has_notion
            ? "Open the web UI to check the Notion sync before generating?"
            : "Open the web UI to add docs & Notion before generating?",
          default: false,
        });
        if (openFirst) {
          await openCmd(repoFolder.id, {});
          await input({
            message: "Press Enter when you're ready to generate…",
          });
        }
      }
    }

    if (shouldGenerate) {
      info("Opening Claude Code — generating the briefing as its first task…");
      console.log();
      const { spawnSync } = await import("node:child_process");
      // Interactive Claude Code, generation as the first user message.
      // --dangerously-skip-permissions so it runs without stopping on tool
      // approvals; KIOKU_NO_AUTOGEN=1 tells the SessionStart hook this session
      // is already handling generation, so it doesn't inject the task twice.
      spawnSync(
        "claude",
        [
          "--dangerously-skip-permissions",
          generateInstruction(summary?.section_order ?? []),
        ],
        {
          cwd: repoRoot,
          stdio: "inherit",
          env: { ...process.env, KIOKU_NO_AUTOGEN: "1" },
        }
      );
    }
  } catch {
    // Backend unreachable or `claude` not on PATH — skip the launch; opening
    // Claude Code later still prompts for generation via the SessionStart hook.
  }
}
