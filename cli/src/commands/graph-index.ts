/**
 * `kioku index` — extract this repo's code graph (Graphify AST, no LLM) and
 * upload it to kioku as a per-file delta, so coding agents can query structure
 * (find_definition / find_references / outline / impact_of) instead of grepping.
 *
 * Incremental: tracks last_indexed_sha in .claude/kioku-state.json and only
 * ships the files changed since. First run ships the whole graph.
 */

import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  statSync,
  rmSync,
} from "node:fs";
import { join, resolve, dirname } from "node:path";
import { execFileSync, spawnSync } from "node:child_process";

import { readMcpEntry } from "../lib/claude.js";
import { headSha } from "../lib/git.js";
import { section, ok, info, warn, bad } from "../lib/banner.js";

interface GraphNode {
  id: string;
  source_file?: string;
  [k: string]: unknown;
}
interface GraphLink {
  source: string;
  target: string;
  source_file?: string;
  [k: string]: unknown;
}

function gitSafe(repoRoot: string, args: string[]): string {
  try {
    return execFileSync("git", args, {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

function readState(repoRoot: string): Record<string, unknown> {
  const p = join(repoRoot, ".claude", "kioku-state.json");
  if (!existsSync(p)) return {};
  try {
    return JSON.parse(readFileSync(p, "utf8")) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function stampState(repoRoot: string, patch: Record<string, unknown>): void {
  const p = join(repoRoot, ".claude", "kioku-state.json");
  mkdirSync(dirname(p), { recursive: true });
  writeFileSync(
    p,
    JSON.stringify({ ...readState(repoRoot), ...patch }, null, 2) + "\n"
  );
}

export function graphifyAvailable(): boolean {
  const r = spawnSync("graphify", ["--version"], { stdio: "ignore" });
  return !r.error && r.status === 0;
}

const LOCK_STALE_MS = 10 * 60 * 1000;

/** Serialize indexing per-repo: init and the on-push detached index (or two
 *  quick pushes) must not run `graphify` on the same graphify-out/ at once —
 *  concurrent writers corrupt graph.json. Returns false if another index holds
 *  a fresh lock. Stale locks (crashed run) are taken over. */
function acquireIndexLock(repoRoot: string): boolean {
  const p = join(repoRoot, ".claude", "kioku-index.lock");
  mkdirSync(dirname(p), { recursive: true });
  try {
    writeFileSync(p, String(process.pid), { flag: "wx" });
    return true;
  } catch {
    try {
      const age = Date.now() - statSync(p).mtimeMs;
      if (age > LOCK_STALE_MS) {
        writeFileSync(p, String(process.pid));
        return true;
      }
    } catch {
      // fall through
    }
    return false;
  }
}

function releaseIndexLock(repoRoot: string): void {
  try {
    rmSync(join(repoRoot, ".claude", "kioku-index.lock"), { force: true });
  } catch {
    // best-effort
  }
}

/** Normalize a path to repo-relative form (strip ./ and an absolute repoRoot
 *  prefix) so extractor output matches `git diff --name-only`. */
function makeNorm(repoRoot: string): (p?: string) => string {
  const prefix = repoRoot.endsWith("/") ? repoRoot : repoRoot + "/";
  return (p?: string) => {
    let s = (p || "").replace(/^\.\//, "");
    if (s.startsWith(prefix)) s = s.slice(prefix.length);
    return s;
  };
}

export async function graphIndex(repoRootArg?: string): Promise<void> {
  const repoRoot = resolve(repoRootArg ?? process.cwd());

  const mcp = readMcpEntry(repoRoot);
  if (!mcp) {
    bad("This repo isn't wired to kioku.", "Run: kioku init");
    process.exitCode = 1;
    return;
  }
  const state = readState(repoRoot);
  const folderId = state.folder_id as string | undefined;
  if (!folderId) {
    bad("No folder binding found in kioku-state.json.", "Run: kioku init");
    process.exitCode = 1;
    return;
  }
  if (!graphifyAvailable()) {
    warn(
      "`graphify` isn't on PATH — skipping code-graph index.",
      "Install it (e.g. `uv tool install graphify`), then re-run `kioku index`."
    );
    return;
  }

  section("Indexing code graph");
  const head = headSha(repoRoot);
  if (!head) {
    bad("Not a git repo with commits.");
    process.exitCode = 1;
    return;
  }
  const lastSha = state.last_indexed_sha as string | undefined;
  const norm = makeNorm(repoRoot);

  if (lastSha === head) {
    info("Already indexed at HEAD — nothing to do.");
    return;
  }

  // Which files to ship. First run: everything. Incremental: git delta.
  const isFirst = !lastSha;
  let changedFiles: string[] = [];
  let deletedFiles: string[] = [];
  if (!isFirst) {
    changedFiles = gitSafe(repoRoot, [
      "diff",
      "--name-only",
      "--diff-filter=ACMRT",
      `${lastSha}..HEAD`,
    ])
      .split("\n")
      .filter(Boolean)
      .map(norm);
    deletedFiles = gitSafe(repoRoot, [
      "diff",
      "--name-only",
      "--diff-filter=D",
      `${lastSha}..HEAD`,
    ])
      .split("\n")
      .filter(Boolean)
      .map(norm);
    if (changedFiles.length === 0 && deletedFiles.length === 0) {
      info("No code changes since last index.");
      stampState(repoRoot, { last_indexed_sha: head });
      return;
    }
  }

  if (!acquireIndexLock(repoRoot)) {
    info("Another `kioku index` is already running — skipping.");
    return;
  }
  try {
    await runExtractionAndUpload(repoRoot, {
      mcp,
      folderId,
      head,
      isFirst,
      changedFiles,
      deletedFiles,
      norm,
    });
  } finally {
    releaseIndexLock(repoRoot);
  }
}

interface UploadCtx {
  mcp: { entry: { url: string }; key: string };
  folderId: string;
  head: string;
  isFirst: boolean;
  changedFiles: string[];
  deletedFiles: string[];
  norm: (p?: string) => string;
}

async function runExtractionAndUpload(
  repoRoot: string,
  { mcp, folderId, head, isFirst, changedFiles, deletedFiles, norm }: UploadCtx
): Promise<void> {
  info("Extracting AST graph (graphify, no LLM)…");
  const ext = spawnSync("graphify", ["update", repoRoot, "--no-cluster"], {
    cwd: repoRoot,
    encoding: "utf8",
  });
  if (ext.status !== 0) {
    bad("graphify extraction failed.", (ext.stderr || "").slice(0, 300));
    process.exitCode = 1;
    return;
  }

  const graphPath = join(repoRoot, "graphify-out", "graph.json");
  if (!existsSync(graphPath)) {
    bad("graphify produced no graph.json.", graphPath);
    process.exitCode = 1;
    return;
  }
  let graph: {
    nodes?: GraphNode[];
    links?: GraphLink[];
    edges?: GraphLink[];
  };
  try {
    graph = JSON.parse(readFileSync(graphPath, "utf8"));
  } catch (err) {
    bad(
      "graph.json was unreadable (partial/concurrent write?).",
      err instanceof Error ? err.message : String(err)
    );
    process.exitCode = 1;
    return;
  }
  const allNodes = graph.nodes ?? [];
  const allEdges = graph.links ?? graph.edges ?? [];

  const changedSet = new Set(changedFiles);
  const nodes = isFirst
    ? allNodes
    : allNodes.filter((n) => changedSet.has(norm(n.source_file)));
  const edges = isFirst
    ? allEdges
    : allEdges.filter((e) => changedSet.has(norm(e.source_file)));

  // First run: the "changed" set is every file present in the graph.
  const filesForDelta = isFirst
    ? [...new Set(allNodes.map((n) => norm(n.source_file)).filter(Boolean))]
    : changedFiles;

  const base = new URL(mcp.entry.url).origin.replace(/:8001$/, ":8000");
  info(`Uploading ${nodes.length} symbols, ${edges.length} edges…`);

  // Upload is best-effort: a transient network/backend hiccup must fail
  // gracefully (clear message, no throw) so a caller like `kioku init` never
  // aborts on it. One quick retry absorbs the common transient case.
  let body:
    | {
        nodes_upserted: number;
        edges_upserted: number;
        node_count: number;
        edge_count: number;
        skipped_shrink?: string[];
      }
    | undefined;
  for (let attempt = 1; attempt <= 2; attempt++) {
    try {
      const res = await fetch(`${base}/api/cli/repo-graph`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${mcp.key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          folder_id: folderId,
          head_sha: head,
          changed_files: filesForDelta,
          deleted_files: deletedFiles,
          nodes,
          edges,
        }),
      });
      if (!res.ok) {
        bad(`Upload failed (${res.status}).`, (await res.text()).slice(0, 300));
        process.exitCode = 1;
        return;
      }
      body = await res.json();
      break;
    } catch (err) {
      if (attempt === 2) {
        bad(
          "Couldn't reach the kioku backend to upload the graph.",
          err instanceof Error ? err.message : String(err)
        );
        process.exitCode = 1;
        return;
      }
    }
  }
  if (!body) return;

  stampState(repoRoot, { last_indexed_sha: head });
  ok(
    `Indexed ${body.nodes_upserted} symbols, ${body.edges_upserted} edges ` +
      `(repo total: ${body.node_count} symbols / ${body.edge_count} edges).`
  );
  if (body.skipped_shrink?.length) {
    warn(
      `Skipped ${body.skipped_shrink.length} file(s) with a suspicious empty re-extraction (kept existing).`
    );
  }
}
