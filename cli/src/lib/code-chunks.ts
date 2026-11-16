/**
 * Symbol-aware code chunking + upload for semantic code search.
 *
 * Reuses the Graphify pass `kioku index` already ran: graph nodes give the
 * symbol names and start lines per file, so chunks split on symbol
 * boundaries (one chunk ≈ one function/class), with a context header that
 * makes concept queries land even when the code never says the concept word.
 * Embedding happens server-side (voyage-code-3, arq worker) — the CLI only
 * ships text + per-file content hashes for incrementality.
 */

import { createHash } from "node:crypto";
import {
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  openSync,
  readSync,
  realpathSync,
} from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

const MAX_FILE_BYTES = 300_000; // skip generated monsters / bundles
const MAX_CHUNK_LINES = 120; // split oversized symbol bodies
const OVERLAP_LINES = 10;
const MIN_CHUNK_LINES = 3; // merge trivial fragments into neighbors
const MAX_CHUNK_CHARS = 18_000; // backend caps content at 20k
const FILES_PER_POST = 40;

const EXT_LANGUAGE: Record<string, string> = {
  py: "python",
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  rs: "rust",
  go: "go",
  java: "java",
  kt: "kotlin",
  c: "c",
  h: "c",
  cpp: "cpp",
  hpp: "cpp",
  cs: "csharp",
  rb: "ruby",
  php: "php",
  swift: "swift",
  sh: "bash",
  sql: "sql",
  proto: "proto",
};

/** Read only a bounded regular file reached without repository-controlled links.
 * Node has no portable openat: pin and compare file/directory identities around
 * the open. Mihari additionally rejects link-bearing checkouts before indexing
 * and serializes checkout updates; this is not a hostile concurrent-FS sandbox.
 */
export function readCodeSource(repoRoot: string, file: string): string | null {
  const parts = file.split(/[\\/]/);
  if (
    isAbsolute(file) ||
    parts.some((part) => !part || part === "." || part === "..")
  )
    return null;
  let fd: number | undefined;
  try {
    const root = realpathSync(repoRoot);
    let path = root;
    const directories = [{ path, info: lstatSync(path) }];
    for (const part of parts.slice(0, -1)) {
      path = join(path, part);
      const info = lstatSync(path);
      if (!info.isDirectory() || info.isSymbolicLink()) return null;
      directories.push({ path, info });
    }
    path = join(path, parts[parts.length - 1]);
    const before = lstatSync(path);
    if (
      !before.isFile() ||
      before.isSymbolicLink() ||
      before.size > MAX_FILE_BYTES
    )
      return null;
    fd = openSync(
      path,
      constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
    );
    const opened = fstatSync(fd);
    if (
      !opened.isFile() ||
      opened.dev !== before.dev ||
      opened.ino !== before.ino ||
      opened.size > MAX_FILE_BYTES
    )
      return null;
    if (realpathSync(path) !== resolve(root, file)) return null;
    for (const directory of directories) {
      const current = lstatSync(directory.path);
      if (
        !current.isDirectory() ||
        current.dev !== directory.info.dev ||
        current.ino !== directory.info.ino
      )
        return null;
    }
    const bytes = Buffer.alloc(MAX_FILE_BYTES + 1);
    let length = 0;
    while (length < bytes.length) {
      const count = readSync(fd, bytes, length, bytes.length - length, null);
      if (!count) break;
      length += count;
    }
    return length > MAX_FILE_BYTES
      ? null
      : bytes.subarray(0, length).toString("utf8");
  } catch {
    return null;
  } finally {
    if (fd !== undefined) closeSync(fd);
  }
}

interface SymbolMark {
  line: number;
  name: string;
}

interface ChunkOut {
  symbol: string | null;
  start_line: number;
  end_line: number;
  content: string;
}

interface FileOut {
  file: string;
  language: string | null;
  file_hash: string;
  chunks: ChunkOut[];
}

export interface CodeChunkNode {
  label?: string;
  source_file?: string;
  source_location?: string;
  file_type?: string;
  [k: string]: unknown;
}

function languageOf(file: string): string | null {
  const ext = file.split(".").pop()?.toLowerCase() ?? "";
  return EXT_LANGUAGE[ext] ?? null;
}

/** Symbol start lines per file, from graphify nodes ("L123" locations).
 *  File-level nodes (label === basename) are skipped — they aren't symbols. */
export function symbolMarksByFile(
  nodes: CodeChunkNode[],
  norm: (p?: string) => string,
): Map<string, SymbolMark[]> {
  const byFile = new Map<string, SymbolMark[]>();
  for (const n of nodes) {
    const file = norm(n.source_file);
    if (!file || !n.label) continue;
    const m = /^L(\d+)/.exec(String(n.source_location ?? ""));
    if (!m) continue;
    const line = parseInt(m[1], 10);
    const base = file.split("/").pop() ?? "";
    if (n.label === base && line <= 1) continue; // the file node itself
    const arr = byFile.get(file) ?? [];
    arr.push({ line, name: String(n.label) });
    byFile.set(file, arr);
  }
  for (const arr of byFile.values()) arr.sort((a, b) => a.line - b.line);
  return byFile;
}

/** Split one file's lines at symbol boundaries; window oversized segments. */
export function chunkFile(
  content: string,
  marks: SymbolMark[],
  header: (symbol: string | null, a: number, b: number) => string,
): ChunkOut[] {
  const lines = content.split("\n");
  if (lines.length === 0) return [];

  // Segment boundaries: line 1 plus each symbol start.
  const starts = [...new Set([1, ...marks.map((m) => m.line)])]
    .filter((l) => l >= 1 && l <= lines.length)
    .sort((a, b) => a - b);

  const segs: { start: number; end: number; symbol: string | null }[] = [];
  for (let i = 0; i < starts.length; i++) {
    const start = starts[i];
    const end = i + 1 < starts.length ? starts[i + 1] - 1 : lines.length;
    if (end < start) continue;
    const sym = marks.find((m) => m.line === start)?.name ?? null;
    segs.push({ start, end, symbol: sym });
  }

  // Merge tiny leading/trailing fragments into the previous segment.
  const merged: typeof segs = [];
  for (const s of segs) {
    const prev = merged[merged.length - 1];
    if (prev && s.end - s.start + 1 < MIN_CHUNK_LINES && s.symbol === null) {
      prev.end = s.end;
    } else {
      merged.push({ ...s });
    }
  }

  const out: ChunkOut[] = [];
  for (const s of merged) {
    for (let a = s.start; a <= s.end; a += MAX_CHUNK_LINES - OVERLAP_LINES) {
      const b = Math.min(a + MAX_CHUNK_LINES - 1, s.end);
      const body = lines.slice(a - 1, b).join("\n");
      if (!body.trim()) {
        if (b >= s.end) break;
        continue;
      }
      const text = header(s.symbol, a, b) + "\n" + body;
      out.push({
        symbol: s.symbol,
        start_line: a,
        end_line: b,
        content:
          text.length > MAX_CHUNK_CHARS ? text.slice(0, MAX_CHUNK_CHARS) : text,
      });
      if (b >= s.end) break;
    }
  }
  return out;
}

interface UploadArgs {
  repoRoot: string;
  base: string; // REST base url
  apiKey: string;
  folderId: string;
  folderName: string;
  files: string[]; // repo-relative candidate files (already normed)
  deletedFiles: string[];
  nodes: CodeChunkNode[];
  norm: (p?: string) => string;
  log: { info: (m: string) => void; warn: (m: string, d?: string) => void };
}

/** Chunk + upload the given files. Returns queued chunk count, or -1 on
 *  hard failure (caller decides whether that's fatal). */
export async function uploadCodeChunks(args: UploadArgs): Promise<number> {
  const { repoRoot, base, apiKey, folderId, folderName } = args;

  // Server-side per-file hashes → skip unchanged files (multi-machine safe).
  let serverHashes: Record<string, string> = {};
  try {
    const res = await fetch(
      `${base}/api/cli/code-chunks?folder_id=${encodeURIComponent(folderId)}`,
      { headers: { Authorization: `Bearer ${apiKey}` } },
    );
    if (res.ok) {
      const body = (await res.json()) as { files?: Record<string, string> };
      serverHashes = body.files ?? {};
    }
  } catch {
    // treat as empty — worst case we re-upload files that didn't change
  }

  const marks = symbolMarksByFile(args.nodes, args.norm);
  const fileOuts: FileOut[] = [];
  let skippedUnchanged = 0;

  for (const file of args.files) {
    const content = readCodeSource(repoRoot, file);
    if (content === null) continue;
    if (content.includes("\u0000")) continue; // binary NUL check

    const hash = createHash("sha256").update(content).digest("hex");
    if (serverHashes[file] === hash) {
      skippedUnchanged++;
      continue;
    }

    const chunks = chunkFile(
      content,
      marks.get(file) ?? [],
      (symbol, a, b) =>
        `[repo ${folderName}] [file ${file}:${a}-${b}]` +
        (symbol ? ` [symbol ${symbol}]` : ""),
    );
    if (chunks.length === 0) continue;
    fileOuts.push({
      file,
      language: languageOf(file),
      file_hash: hash,
      chunks,
    });
  }

  if (fileOuts.length === 0 && args.deletedFiles.length === 0) {
    args.log.info(
      skippedUnchanged > 0
        ? `Code chunks: all ${skippedUnchanged} files unchanged on server.`
        : "Code chunks: nothing to upload.",
    );
    return 0;
  }

  let queued = 0;
  for (let i = 0; i < Math.max(fileOuts.length, 1); i += FILES_PER_POST) {
    const slice = fileOuts.slice(i, i + FILES_PER_POST);
    const payload = {
      folder_id: folderId,
      files: slice,
      // deleted files ride the first request only
      deleted_files: i === 0 ? args.deletedFiles : [],
    };
    try {
      const res = await fetch(`${base}/api/cli/code-chunks`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        args.log.warn(
          `Code-chunk upload failed (${res.status}).`,
          (await res.text()).slice(0, 200),
        );
        return -1;
      }
      const body = (await res.json()) as { chunks_queued?: number };
      queued += body.chunks_queued ?? 0;
    } catch (err) {
      args.log.warn(
        "Couldn't reach the backend for code-chunk upload.",
        err instanceof Error ? err.message : String(err),
      );
      return -1;
    }
    if (fileOuts.length === 0) break;
  }
  return queued;
}
