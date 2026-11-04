/** Lossless local originals. No models, credentials, or journal mutations. */
import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  existsSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  readSync,
  readdirSync,
  realpathSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { configDir } from "./config.js";
import { type AgentName } from "./agent-journal.js";

export const EVIDENCE_SCHEMA = 1;
export const SEGMENT_TARGET = 1024 * 1024;
export const OBJECT_LIMIT = 64 * 1024 * 1024;
export interface EvidenceHook {
  cwd?: string;
  session_id?: string;
  transcript_path?: string;
  agent_id?: string;
  agent_transcript_path?: string;
  hook_event_name?: string;
  last_assistant_message?: string;
}
export interface EvidenceObject {
  id: string;
  kind: "segment" | "attachment";
  stream_id: string;
  generation: number;
  sha256: string;
  byte_length: number;
  path: string;
  source_start?: number;
  source_end?: number;
  first_record?: number;
  last_record?: number;
  record_count?: number;
  original_name?: string;
  source_event_id?: string;
  oversized_record?: boolean;
}
export interface EvidenceLink {
  journal_entry_id: string;
  journal_date: string;
  start_event_id: string;
  end_event_id?: string;
}
export interface EvidenceManifest {
  schema: 1;
  agent: AgentName;
  native_session_id: string;
  native_root_session_id: string;
  native_parent_session_id?: string;
  producer_id: string;
  revision: number;
  objects: EvidenceObject[];
  journal_links: EvidenceLink[];
  children: string[];
  gaps: Array<{ code: string; event_id?: string; name?: string }>;
  lifecycle: { status: "observed" | "ended"; ended_at: string | null };
  coverage?: {
    stream_id: string;
    generation: number;
    captured_through: number;
    observed_size: number;
    pending_bytes: number;
  };
  captured_at: string;
}
interface Cursor {
  identity: string;
  stream_id: string;
  generation: number;
  offset: number;
  record_sequence: number;
  head_hash: string;
  boundary_hash: string;
  mtime_ms: number;
  size: number;
  latest_turn?: { id: string; event_id: string };
  attachment_refs?: Array<{ path: string; event_id: string }>;
}
export interface Source {
  path: string;
  agent: AgentName;
  session: string;
  root: string;
  parent?: string;
  ancestors?: string[];
}
export const hash = (data: string | Buffer): string =>
  createHash("sha256").update(data).digest("hex");
export function eventId(
  folder: string,
  source: Source,
  stream: string,
  generation: number,
  sequence: number,
): string {
  return hash(
    JSON.stringify([
      folder,
      source.agent,
      source.session,
      stream,
      generation,
      sequence,
    ]),
  );
}
function safe(id: string): string {
  if (/^[A-Za-z0-9_-]{1,180}$/.test(id)) return id;
  // Retain the original opaque identity in metadata without treating it as a path.
  return "id-" + hash(id);
}
export const evidenceStateDir = (root: string): string =>
  join(root, ".kioku", "memory", ".evidence-state");
export function sessionDir(root: string, source: Source): string {
  const base = join(
    root,
    ".kioku",
    "memory",
    "originals",
    source.agent,
    safe(source.root),
  );
  if (source.session === source.root) return base;
  let path = base;
  for (const ancestor of source.ancestors ||
    (source.parent && source.parent !== source.root ? [source.parent] : []))
    if (ancestor !== source.root && ancestor !== source.session)
      path = join(path, "subagents", safe(ancestor));
  return join(path, "subagents", safe(source.session));
}
export function readJson<T>(path: string, fallback: T): T {
  if (!existsSync(path)) return fallback;
  return JSON.parse(readFileSync(path, "utf8")) as T;
}
export function writeAtomic(path: string, data: string | Buffer): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  const fd = openSync(temporary, "wx", 0o600);
  try {
    writeFileSync(fd, data);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(temporary, path);
  try {
    const dir = openSync(dirname(path), "r");
    try {
      fsyncSync(dir);
    } finally {
      closeSync(dir);
    }
  } catch {
    /* directory fsync unsupported on Windows */
  }
}
export function writeJson(path: string, value: unknown): void {
  writeAtomic(path, JSON.stringify(value, null, 2) + "\n");
}
export async function withEvidenceLock<T>(
  path: string,
  work: () => T | Promise<T>,
  waitMs = 5000,
): Promise<T> {
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const owner = `${process.pid}:${randomUUID()}`,
    deadline = Date.now() + waitMs;
  const candidate = path + ".candidate-" + randomUUID();
  mkdirSync(candidate, { mode: 0o700 });
  writeFileSync(join(candidate, "owner"), owner, { mode: 0o600 });
  let acquired = false;
  try {
    while (!acquired) {
      try {
        renameSync(candidate, path);
        acquired = true;
        break;
      } catch (error) {
        if (
          !["EEXIST", "ENOTEMPTY", "EPERM"].includes(
            (error as NodeJS.ErrnoException).code || "",
          )
        )
          throw error;
        try {
          const existing = readFileSync(join(path, "owner"), "utf8"),
            pid = Number(existing.split(":")[0]);
          let dead = false;
          try {
            process.kill(pid, 0);
          } catch (e) {
            dead = (e as NodeJS.ErrnoException).code === "ESRCH";
          }
          if (dead) {
            // A fixed occupied retirement destination prevents a second
            // contender with the old owner from moving a new live lock.
            const retired = join(
              dirname(path),
              ".retired-locks",
              hash(path),
              hash(existing),
            );
            mkdirSync(dirname(retired), { recursive: true, mode: 0o700 });
            try {
              renameSync(path, retired);
            } catch {
              /* owner already retired */
            }
            continue;
          }
        } catch {
          /* another process released or acquired the lock */
        }
        if (Date.now() >= deadline) throw new Error("evidence_lock_busy");
        await new Promise((done) => setTimeout(done, 25));
      }
    }
    return await work();
  } finally {
    if (!acquired) rmSync(candidate, { recursive: true, force: true });
    if (acquired) {
      try {
        if (readFileSync(join(path, "owner"), "utf8") === owner)
          rmSync(path, { recursive: true, force: true });
      } catch {
        /* no longer owns path */
      }
    }
  }
}
export function producerId(): string {
  const path = join(configDir(), "evidence-producer.json");
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  try {
    writeFileSync(path, JSON.stringify({ id: randomUUID() }), {
      flag: "wx",
      mode: 0o600,
    });
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
  }
  return readJson<{ id: string }>(path, { id: "" }).id;
}
function readRange(path: string, start: number, length: number): Buffer {
  const fd = openSync(path, "r"),
    buffer = Buffer.alloc(length);
  try {
    let got = 0;
    while (got < length) {
      const n = readSync(fd, buffer, got, length - got, start + got);
      if (!n) break;
      got += n;
    }
    return buffer.subarray(0, got);
  } finally {
    closeSync(fd);
  }
}
function prefixHash(path: string, length: number): string {
  const digest = createHash("sha256"),
    fd = openSync(path, "r"),
    buffer = Buffer.alloc(64 * 1024);
  try {
    let position = 0;
    while (position < length) {
      const count = readSync(
        fd,
        buffer,
        0,
        Math.min(buffer.length, length - position),
        position,
      );
      if (!count) break;
      digest.update(buffer.subarray(0, count));
      position += count;
    }
    return digest.digest("hex");
  } finally {
    closeSync(fd);
  }
}
export function nativeMetadata(path: string): Record<string, unknown> {
  if (!existsSync(path)) return {};
  for (const line of readRange(
    path,
    0,
    Math.min(statSync(path).size, 128 * 1024),
  )
    .toString("utf8")
    .split("\n")
    .slice(0, 10)) {
    try {
      const record = JSON.parse(line);
      if (record.type === "session_meta") return record.payload ?? {};
      if (typeof record.cwd === "string") return { cwd: record.cwd };
    } catch {
      /* incomplete metadata */
    }
  }
  return {};
}
export function sourceFromHook(
  agent: AgentName,
  payload: EvidenceHook,
): Source | null {
  if (!payload.session_id) return null;
  let source = payload.agent_transcript_path || payload.transcript_path;
  if (!source) return null;
  source = resolve(source);
  let session = payload.session_id,
    parent: string | undefined;
  if (
    payload.agent_transcript_path ||
    (agent === "codex" &&
      payload.hook_event_name === "SubagentStart" &&
      payload.agent_id)
  ) {
    session = payload.agent_id || "";
    parent = payload.session_id;
  }
  const meta = agent === "codex" ? nativeMetadata(source) : {};
  if (typeof meta.id === "string") session = meta.id;
  if (typeof meta.parent_thread_id === "string") parent = meta.parent_thread_id;
  const root =
    typeof meta.session_id === "string" && meta.session_id !== session
      ? meta.session_id
      : parent || session;
  return session ? { path: source, agent, session, root, parent } : null;
}
export function readManifest(
  root: string,
  source: Source,
): EvidenceManifest | null {
  return readJson<EvidenceManifest | null>(
    join(sessionDir(root, source), "manifest.json"),
    null,
  );
}
export async function registerSource(
  root: string,
  source: Source,
): Promise<void> {
  const dir = evidenceStateDir(root),
    file = join(dir, "sources.json");
  await withEvidenceLock(join(dir, "registry.lock"), () => {
    const sources = readJson<Source[]>(file, []),
      key = hash(JSON.stringify([source.agent, source.session, source.path]));
    if (
      !sources.some(
        (s) => hash(JSON.stringify([s.agent, s.session, s.path])) === key,
      )
    )
      writeJson(file, [...sources, source]);
  });
}
export function sourcesInRepo(root: string): Source[] {
  return readJson<Source[]>(join(evidenceStateDir(root), "sources.json"), []);
}
function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  if (value && typeof value === "object")
    return Object.values(value).flatMap(strings);
  return [];
}
function immutable(path: string, bytes: Buffer): void {
  if (existsSync(path)) {
    if (hash(readFileSync(path)) !== hash(bytes))
      throw new Error("evidence_object_conflict");
    return;
  }
  writeAtomic(path, bytes);
}
export async function captureSource(
  root: string,
  folder: string,
  source: Source,
  options: {
    target?: number;
    maxBytes?: number;
    end?: boolean;
    producer?: string;
    lockWaitMs?: number;
    progress?: boolean;
    finalizeJournal?: boolean;
    endOffset?: number;
  } = {},
): Promise<EvidenceManifest> {
  const dir = sessionDir(root, source),
    stateDir = evidenceStateDir(root);
  return withEvidenceLock(
    join(dir, ".capture.lock"),
    () => {
      const producer = options.producer || producerId(),
        now = new Date().toISOString();
      const m: EvidenceManifest = readManifest(root, source) || {
        schema: 1,
        agent: source.agent,
        native_session_id: source.session,
        native_root_session_id: source.root,
        native_parent_session_id: source.parent,
        producer_id: producer,
        revision: 0,
        objects: [],
        journal_links: [],
        children: [],
        gaps: [],
        lifecycle: { status: "observed", ended_at: null },
        captured_at: now,
      };
      if (!source.parent) delete m.native_parent_session_id;
      const statePath = join(
        stateDir,
        "cursors",
        hash(
          JSON.stringify([source.agent, source.session, source.path, producer]),
        ) + ".json",
      );
      let cursor = readJson<Cursor | null>(statePath, null);
      m.children = sourcesInRepo(root)
        .filter(
          (child) =>
            child.agent === source.agent && child.parent === source.session,
        )
        .map((child) => child.session);
      if (!existsSync(source.path)) {
        m.gaps = [
          ...m.gaps.filter((g) => g.code !== "source_unreadable"),
          { code: "source_unreadable" },
        ];
        writeJson(join(dir, "manifest.json"), m);
        return m;
      }
      const stat = statSync(source.path),
        identity = `${stat.dev}:${stat.ino}`;
      const boundary = (offset: number) =>
        hash(
          readRange(
            source.path,
            Math.max(0, offset - 4096),
            Math.min(offset, 4096),
          ),
        );
      const head = hash(
        readRange(
          source.path,
          0,
          Math.min(stat.size, cursor ? cursor.offset : 4096, 4096),
        ),
      );
      let rewritten = false;
      if (
        cursor &&
        stat.size === cursor.size &&
        stat.mtimeMs !== cursor.mtime_ms &&
        cursor.offset > 0
      ) {
        // Native append checkpoints use only boundary fingerprints. Same-size
        // rewrites are rare and require a full prefix comparison to catch edits
        // outside those fingerprints without rereading history on every append.
        const priorHash = createHash("sha256");
        for (const object of m.objects
          .filter(
            (o) =>
              o.kind === "segment" &&
              o.stream_id === cursor!.stream_id &&
              o.generation === cursor!.generation,
          )
          .sort((a, b) => a.source_start! - b.source_start!))
          priorHash.update(readFileSync(join(dir, object.path)));
        rewritten =
          prefixHash(source.path, cursor.offset) !== priorHash.digest("hex");
      }
      const changed =
        cursor &&
        (rewritten ||
          cursor.identity !== identity ||
          stat.size < cursor.offset ||
          cursor.head_hash !== head ||
          cursor.boundary_hash !== boundary(cursor.offset));
      if (!cursor || changed)
        cursor = {
          identity,
          stream_id: hash(
            JSON.stringify([
              producer,
              source.agent,
              source.session,
              source.path,
            ]),
          ).slice(0, 32),
          generation: (cursor?.generation || 0) + 1,
          offset: 0,
          record_sequence: 0,
          head_hash: "",
          boundary_hash: "",
          mtime_ms: stat.mtimeMs,
          size: stat.size,
        };
      const capturedBefore = cursor.offset;
      const snapshotEnd = Math.min(stat.size, options.endOffset ?? stat.size);
      const bytes = readRange(
        source.path,
        cursor.offset,
        Math.max(
          0,
          Math.min(
            snapshotEnd - cursor.offset,
            options.maxBytes || OBJECT_LIMIT,
          ),
        ),
      );
      const lastNewline = bytes.lastIndexOf(10);
      let complete =
        lastNewline < 0 ? Buffer.alloc(0) : bytes.subarray(0, lastNewline + 1);
      if (
        options.progress &&
        complete.length < (options.target || SEGMENT_TARGET)
      )
        complete = Buffer.alloc(0);
      m.gaps = m.gaps.filter(
        (g) =>
          !["source_unreadable", "partial_tail", "blocked_size_limit"].includes(
            g.code,
          ),
      );
      if (lastNewline + 1 < bytes.length)
        m.gaps.push({
          code:
            bytes.length >= OBJECT_LIMIT && lastNewline < 0
              ? "blocked_size_limit"
              : "partial_tail",
        });
      let start = 0,
        recordStart = cursor.record_sequence + 1,
        pendingStart = cursor.offset,
        offset = cursor.offset,
        current: Buffer[] = [],
        size = 0,
        count = 0;
      const records: Array<{
        record: Record<string, unknown> | null;
        sequence: number;
        line: number;
      }> = [];
      const flush = () => {
        if (!size) return;
        const data = Buffer.concat(current),
          sha = hash(data),
          id = hash(
            JSON.stringify([
              source.session,
              cursor!.stream_id,
              cursor!.generation,
              pendingStart,
              sha,
            ]),
          );
        const path = `segments/${cursor!.stream_id}-g${cursor!.generation}-${pendingStart}-${sha.slice(0, 16)}.jsonl`;
        immutable(join(dir, path), data);
        if (!m.objects.some((o) => o.id === id))
          m.objects.push({
            id,
            kind: "segment",
            stream_id: cursor!.stream_id,
            generation: cursor!.generation,
            sha256: sha,
            byte_length: data.length,
            path,
            source_start: pendingStart,
            source_end: offset,
            first_record: recordStart,
            last_record: recordStart + count - 1,
            record_count: count,
            oversized_record: data.length > (options.target || SEGMENT_TARGET),
          });
        pendingStart = offset;
        recordStart += count;
        current = [];
        size = 0;
        count = 0;
      };
      for (let n = 0; n < complete.length; n++)
        if (complete[n] === 10) {
          const line = complete.subarray(start, n + 1);
          start = n + 1;
          if (size && size + line.length > (options.target || SEGMENT_TARGET))
            flush();
          let record: Record<string, unknown> | null = null;
          try {
            if (!Buffer.from(line.toString("utf8")).equals(line))
              throw new Error("invalid_utf8");
            record = JSON.parse(line.toString("utf8"));
          } catch {
            m.gaps.push({
              code: "parse_error",
              event_id: eventId(
                folder,
                source,
                cursor.stream_id,
                cursor.generation,
                cursor.record_sequence + 1,
              ),
            });
          }
          cursor.record_sequence++;
          records.push({
            record,
            sequence: cursor.record_sequence,
            line: cursor.record_sequence - 1,
          });
          if (record) {
            const message = record.message as { content?: unknown } | undefined;
            const payload = record.payload as
              | Record<string, unknown>
              | undefined;
            const item = payload?.item as
              | { type?: string; id?: string; content?: unknown }
              | undefined;
            const text = (content: unknown): string =>
              typeof content === "string"
                ? content
                : Array.isArray(content)
                  ? content
                      .filter((part) =>
                        ["text", "input_text", "output_text"].includes(
                          part?.type,
                        ),
                      )
                      .map((part) => part.text || "")
                      .join("\n")
                  : "";
            let turn: string | undefined;
            if (
              source.agent === "claude_code" &&
              record.type === "user" &&
              !record.isMeta &&
              text(message?.content).trim()
            )
              turn = String(record.uuid ?? cursor.record_sequence - 1);
            if (
              source.agent === "codex" &&
              record.type === "event_msg" &&
              payload?.type === "user_message" &&
              String(payload.message ?? "").trim()
            )
              turn = String(payload.id ?? cursor.record_sequence - 1);
            if (
              source.agent === "codex" &&
              record.type === "event_msg" &&
              payload?.type === "item_completed" &&
              item?.type === "UserMessage" &&
              text(item.content).trim()
            )
              turn = String(item.id ?? cursor.record_sequence - 1);
            if (turn)
              cursor.latest_turn = {
                id: turn,
                event_id: eventId(
                  folder,
                  source,
                  cursor.stream_id,
                  cursor.generation,
                  cursor.record_sequence,
                ),
              };
          }
          current.push(line);
          size += line.length;
          count++;
          offset += line.length;
        }
      flush();
      for (const item of records) {
        if (!item.record) continue;
        const locator = eventId(
          folder,
          source,
          cursor.stream_id,
          cursor.generation,
          item.sequence,
        );
        for (const text of strings(item.record)) {
          if (/Warning: truncated output|Output truncated upstream/i.test(text))
            m.gaps.push({ code: "upstream_truncated", event_id: locator });
          for (const match of text.matchAll(
            /Full output saved to: ([^\r\n]+)/g,
          )) {
            const ref = { path: match[1].trim(), event_id: locator };
            cursor.attachment_refs = [
              ...(cursor.attachment_refs || []).filter(
                (r) => r.path !== ref.path,
              ),
              ref,
            ];
          }
        }
      }
      m.gaps = m.gaps.filter(
        (g) =>
          !["attachment_missing", "attachment_outside_source"].includes(g.code),
      );
      for (const reference of cursor.attachment_refs || []) {
        const ref = reference.path,
          locator = reference.event_id,
          allowed = source.parent
            ? resolve(dirname(source.path), "..")
            : join(dirname(source.path), source.session);
        let path: string;
        try {
          path = realpathSync(ref);
          const rel = relative(realpathSync(allowed), path);
          if (rel.startsWith("..") || isAbsolute(rel))
            throw new Error("outside");
        } catch {
          m.gaps.push({
            code: existsSync(ref)
              ? "attachment_outside_source"
              : "attachment_missing",
            event_id: locator,
          });
          continue;
        }
        if (statSync(path).size > OBJECT_LIMIT) {
          m.gaps.push({ code: "blocked_size_limit", event_id: locator });
          continue;
        }
        const data = readFileSync(path),
          sha = hash(data),
          id = hash(JSON.stringify([source.session, "attachment", sha])),
          objectPath = "attachments/" + sha;
        immutable(join(dir, objectPath), data);
        if (!m.objects.some((o) => o.id === id))
          m.objects.push({
            id,
            kind: "attachment",
            stream_id: cursor.stream_id,
            generation: cursor.generation,
            sha256: sha,
            byte_length: data.length,
            path: objectPath,
            original_name: path.split(/[\\/]/).pop(),
            source_event_id: locator,
          });
      }
      // Existing journal alias conventions are reused, but no journal content is changed.
      if (
        options.finalizeJournal &&
        cursor.latest_turn &&
        !source.parent &&
        cursor.record_sequence &&
        capturedBefore <= snapshotEnd &&
        offset >= snapshotEnd
      ) {
        const tail = cursor.record_sequence;
        const id = `${source.agent}:${source.session}:${cursor.latest_turn.id}`;
        const link = {
          journal_entry_id: id,
          journal_date: now.slice(0, 10),
          start_event_id: cursor.latest_turn.event_id,
          end_event_id: eventId(
            folder,
            source,
            cursor.stream_id,
            cursor.generation,
            tail,
          ),
        };
        m.journal_links = [
          ...m.journal_links.filter((l) => l.journal_entry_id !== id),
          link,
        ];
      }
      const prior = readManifest(root, source);
      cursor.offset = offset;
      cursor.head_hash = hash(
        readRange(source.path, 0, Math.min(offset, 4096)),
      );
      cursor.boundary_hash = boundary(offset);
      cursor.mtime_ms = stat.mtimeMs;
      cursor.size = stat.size;
      m.coverage = {
        stream_id: cursor.stream_id,
        generation: cursor.generation,
        captured_through: offset,
        observed_size: stat.size,
        pending_bytes: Math.max(0, stat.size - offset),
      };
      if (options.end) m.lifecycle = { status: "ended", ended_at: now };
      else if (complete.length)
        m.lifecycle = { status: "observed", ended_at: null };
      m.gaps = [...new Map(m.gaps.map((g) => [JSON.stringify(g), g])).values()];
      if (
        !prior ||
        complete.length ||
        JSON.stringify(prior.gaps) !== JSON.stringify(m.gaps) ||
        JSON.stringify(prior.lifecycle) !== JSON.stringify(m.lifecycle) ||
        JSON.stringify(prior.objects) !== JSON.stringify(m.objects) ||
        JSON.stringify(prior.journal_links) !==
          JSON.stringify(m.journal_links) ||
        JSON.stringify(prior.coverage) !== JSON.stringify(m.coverage) ||
        JSON.stringify(prior.children) !== JSON.stringify(m.children)
      ) {
        m.revision++;
        m.captured_at = now;
        writeJson(join(dir, "manifest.json"), m);
      }
      // Manifest precedes cursor: after a crash, deterministic object IDs make replay safe.
      writeJson(statePath, cursor);
      return m;
    },
    options.lockWaitMs ?? 5000,
  );
}

export function discoverClaudeChildren(source: Source): Source[] {
  if (source.agent !== "claude_code" || !existsSync(source.path)) return [];
  const dir = join(dirname(source.path), source.session, "subagents");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((n) => /^agent-.+\.jsonl$/.test(n))
    .map((n) => ({
      path: join(dir, n),
      agent: source.agent,
      session: n.slice(6, -6),
      root: source.root,
      parent: source.session,
      ancestors: [...(source.ancestors || []), source.session],
    }));
}
