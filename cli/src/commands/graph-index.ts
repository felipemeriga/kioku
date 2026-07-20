/**
 * `kioku index` — extract this repo's code graph (Graphify AST, no LLM) and
 * upload it to kioku as a per-file delta, so coding agents can query structure
 * (find_definition / find_references / outline / impact_of) instead of grepping.
 *
 * Incremental: tracks last_indexed_sha in .claude/kioku-state.json and only
 * ships the files changed since. First run ships the whole graph.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
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

function graphifyAvailable(): boolean {
  const r = spawnSync("graphify", ["--version"], { stdio: "ignore" });
  return !r.error && r.status === 0;
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

export async function graphIndex(): Promise<void> {
  const repoRoot = resolve(process.cwd());

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
  const graph = JSON.parse(readFileSync(graphPath, "utf8")) as {
    nodes?: GraphNode[];
    links?: GraphLink[];
    edges?: GraphLink[];
  };
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
  const body = (await res.json()) as {
    nodes_upserted: number;
    edges_upserted: number;
    node_count: number;
    edge_count: number;
    skipped_shrink?: string[];
  };
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
