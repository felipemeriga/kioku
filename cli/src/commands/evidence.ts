import { evidenceHookCapabilities } from "../lib/agent-evidence-capabilities.js";
/** Durable hook dispatch + bounded deterministic capture worker. No model calls. */
import { execFileSync, spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  realpathSync,
  rmSync,
  statSync,
} from "node:fs";
import { homedir } from "node:os";
import { join, relative, resolve, isAbsolute } from "node:path";
import { randomUUID } from "node:crypto";
import { cliProcessArgs, readMcpEntry, readRepoState } from "../lib/claude.js";
import { type AgentName } from "../lib/agent-journal.js";
import {
  nativeMetadata,
  captureSource,
  discoverClaudeChildren,
  evidenceStateDir,
  hash,
  readJson,
  readManifest,
  registerSource,
  sessionDir,
  sourceFromHook,
  sourcesInRepo,
  withEvidenceLock,
  writeJson,
  type EvidenceHook,
  type Source,
} from "../lib/agent-evidence.js";
import { syncEvidence } from "../lib/agent-evidence-sync.js";

interface Job {
  token: string;
  source: Source;
  event: string;
  enqueued_at: string;
  observed_size: number;
}
function repoRoot(cwd: string): string | null {
  try {
    return execFileSync("git", ["rev-parse", "--show-toplevel"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null;
  }
}
function bound(root: string): string | null {
  return readMcpEntry(root) ? readRepoState(root)?.folder_id || null : null;
}
export function evidenceEnabled(root: string): boolean {
  return (
    readJson<{ original_evidence_enabled?: boolean }>(
      join(evidenceStateDir(root), "settings.json"),
      {},
    ).original_evidence_enabled !== false
  );
}
export function setEvidenceEnabled(root: string, enabled: boolean): void {
  writeJson(join(evidenceStateDir(root), "settings.json"), {
    original_evidence_enabled: enabled,
  });
}
async function payload(): Promise<EvidenceHook> {
  let value = "";
  for await (const chunk of process.stdin) {
    value += String(chunk);
    if (value.length > 256 * 1024)
      throw new Error("evidence_hook_payload_too_large");
  }
  try {
    return JSON.parse(value) as EvidenceHook;
  } catch {
    return {};
  }
}
function authorizedNativePath(agent: AgentName, source: string): boolean {
  const base =
    agent === "codex"
      ? join(process.env.CODEX_HOME || join(homedir(), ".codex"), "sessions")
      : join(
          process.env.CLAUDE_CONFIG_DIR || join(homedir(), ".claude"),
          "projects",
        );
  const rel = relative(resolve(base), resolve(source));
  if (rel === "" || rel.startsWith("..") || isAbsolute(rel)) return false;
  if (existsSync(source)) {
    const actual = relative(realpathSync(base), realpathSync(source));
    return actual !== "" && !actual.startsWith("..") && !isAbsolute(actual);
  }
  return true;
}
export async function dispatchEvidence(
  root: string,
  agent: AgentName,
  input: EvidenceHook,
): Promise<string | null> {
  const folder = bound(root);
  if (!folder || !evidenceEnabled(root)) return null;
  // Codex Stop may omit transcript_path although earlier checkpoints registered
  // the native session. Resolve that same session, never another transcript.
  if (
    agent === "codex" &&
    !input.agent_transcript_path &&
    !input.transcript_path &&
    input.session_id
  ) {
    const registered = sourcesInRepo(root).find(
      (candidate) =>
        candidate.agent === agent && candidate.session === input.session_id,
    );
    let path = registered?.path;
    if (!path) {
      const base = join(
        process.env.CODEX_HOME || join(homedir(), ".codex"),
        "sessions",
      );
      const directories = new Set<string>();
      for (const timestamp of [Date.now(), Date.now() - 86400000]) {
        const date = new Date(timestamp);
        for (const utc of [false, true])
          directories.add(
            join(
              base,
              String(utc ? date.getUTCFullYear() : date.getFullYear()),
              String((utc ? date.getUTCMonth() : date.getMonth()) + 1).padStart(
                2,
                "0",
              ),
              String(utc ? date.getUTCDate() : date.getDate()).padStart(2, "0"),
            ),
          );
      }
      for (const dir of directories) {
        if (!existsSync(dir)) continue;
        const file = readdirSync(dir).find((name) =>
          name.endsWith(`-${input.session_id}.jsonl`),
        );
        if (file) {
          path = join(dir, file);
          break;
        }
      }
    }
    if (path) input = { ...input, transcript_path: path };
  }
  const suppliedPath = input.agent_transcript_path || input.transcript_path;
  if (!suppliedPath || !authorizedNativePath(agent, suppliedPath)) return null;
  const source = sourceFromHook(agent, input);
  if (!source || !authorizedNativePath(agent, source.path)) return null;
  const nativeCwd = nativeMetadata(source.path).cwd;
  if (typeof nativeCwd === "string") {
    const nativeRoot = repoRoot(nativeCwd);
    if (!nativeRoot || realpathSync(nativeRoot) !== realpathSync(root))
      return null;
  }
  const parent =
    source.parent &&
    sourcesInRepo(root).find(
      (s) => s.agent === agent && s.session === source.parent,
    );
  if (parent) {
    source.root = parent.root;
    source.ancestors = [...(parent.ancestors || []), parent.session];
  }
  await registerSource(root, source);
  const pending = join(evidenceStateDir(root), "pending"),
    size = existsSync(source.path) ? statSync(source.path).size : 0;
  const event = input.hook_event_name || "Stop";
  const id = hash(
    JSON.stringify([
      agent,
      source.session,
      source.path,
      ["Stop", "PreCompact", "SessionEnd", "SubagentStop"].includes(event)
        ? [event, size]
        : "progress",
    ]),
  );
  const job: Job = {
    token: randomUUID(),
    source,
    event,
    observed_size: size,
    enqueued_at: new Date().toISOString(),
  };
  writeJson(join(pending, id + ".json"), job);
  if (["PreCompact", "SessionEnd"].includes(job.event)) {
    try {
      await captureSource(root, folder, source, {
        maxBytes: 4 * 1024 * 1024,
        lockWaitMs: 50,
        end: job.event === "SessionEnd",
      });
    } catch {
      /* retry intent was durably written before bounded local preservation */
    }
  }
  if (
    agent === "claude_code" &&
    input.hook_event_name === "SubagentStart" &&
    input.agent_id &&
    !input.agent_transcript_path
  ) {
    const child = {
      path: join(
        resolve(source.path, ".."),
        source.session,
        "subagents",
        `agent-${input.agent_id}.jsonl`,
      ),
      agent,
      session: input.agent_id,
      root: source.root,
      parent: source.session,
    };
    await registerSource(root, child);
  }
  return root;
}
export async function evidenceCapture(agent: AgentName): Promise<void> {
  if (
    process.env.KIOKU_MEMORY_CAPTURE_ACTIVE ||
    process.env.KIOKU_EVIDENCE_CAPTURE_ACTIVE
  )
    return;
  const input = await payload(),
    root = repoRoot(resolve(input.cwd || process.cwd()));
  if (!root || !(await dispatchEvidence(root, agent, input))) return;
  spawnEvidenceWorker(root);
}
function spawnEvidenceWorker(root: string, retryAt?: number): void {
  const invocation = cliProcessArgs(["evidence-worker", "--root", root]);
  const child = spawn(invocation.command, invocation.args, {
    cwd: root,
    detached: true,
    stdio: "ignore",
    env: {
      ...process.env,
      KIOKU_EVIDENCE_CAPTURE_ACTIVE: "1",
      ...(retryAt ? { KIOKU_EVIDENCE_RETRY_AT: String(retryAt) } : {}),
    },
  });
  child.on("error", () => {});
  child.unref();
}
export async function evidenceWorker(
  root = process.cwd(),
  force = false,
  options: { scheduleRetry?: (root: string, at: number) => void } = {},
): Promise<void> {
  const folder = bound(root);
  if (!folder || !evidenceEnabled(root)) return;
  const state = evidenceStateDir(root),
    pending = join(state, "pending");
  mkdirSync(pending, { recursive: true, mode: 0o700 });
  // One repository worker coalesces checkpoints; it can never fan out unlimited
  // network jobs. This is stricter than the per-repo concurrency ceiling.
  const deferred = Number(process.env.KIOKU_EVIDENCE_RETRY_AT || 0);
  delete process.env.KIOKU_EVIDENCE_RETRY_AT;
  if (deferred)
    await withEvidenceLock(
      join(state, "scheduled-retry.lock"),
      async () => {
        const wait = Math.max(0, Math.min(300_000, deferred - Date.now()));
        if (wait) await new Promise((resolve) => setTimeout(resolve, wait));
      },
      0,
    );
  const attempted = new Set<string>();
  let incompleteCapture = false;
  await withEvidenceLock(
    join(state, "worker.lock"),
    async () => {
      const deadline = Date.now() + 90_000;
      const visited = new Set<string>();
      const locallyPreserved = new Set<string>();
      while (Date.now() < deadline) {
        const jobs = readdirSync(pending)
          .filter((n) => n.endsWith(".json"))
          .map((n) => ({
            path: join(pending, n),
            job: readJson<Job>(join(pending, n), null as unknown as Job),
          }));
        const registered = sourcesInRepo(root);
        const cursorPath = join(state, "worker-cursor.json");
        const last = readJson<{ path?: string }>(cursorPath, {}).path;
        const pivot = registered.findIndex((source) => source.path === last);
        const rotated = [
          ...registered.slice(pivot + 1),
          ...registered.slice(0, pivot + 1),
        ];
        // Explicit hook checkpoints take precedence over background rescans.
        // Retain a round-robin cursor before I/O so a slow/offline source cannot
        // consume every worker budget and permanently starve later sessions.
        const queued = new Set(jobs.map(({ job }) => job.source.path));
        const sources = [
          ...rotated.filter((source) => queued.has(source.path)),
          ...rotated.filter((source) => !queued.has(source.path)),
        ];
        for (const { job } of jobs)
          if (!sources.some((source) => source.path === job.source.path))
            attempted.add(job.token);
        if (
          !jobs.some(({ job }) => !attempted.has(job.token)) &&
          sources.every((source) => visited.has(source.path))
        )
          break;
        // Preserve a bounded native checkpoint for every queued source before
        // any network operation can consume this invocation's upload budget.
        // Use the earliest checkpoint so Stop aliases retain their exact range.
        for (const source of sources) {
          const checkpoint = jobs
            .filter(({ job }) => job.source.path === source.path)
            .sort((a, b) => a.job.observed_size - b.job.observed_size)[0]?.job;
          if (!checkpoint || locallyPreserved.has(source.path)) continue;
          locallyPreserved.add(source.path);
          if (!authorizedNativePath(source.agent, source.path)) continue;
          try {
            await captureSource(root, folder, source, {
              maxBytes: 4 * 1024 * 1024,
              lockWaitMs: 50,
              endOffset: checkpoint.observed_size || undefined,
              progress: checkpoint.event === "PostToolUse",
              finalizeJournal: checkpoint.event === "Stop",
              end: ["SessionEnd", "SubagentStop"].includes(checkpoint.event),
            });
          } catch {
            // The durable job remains; the normal capture pass records errors.
          }
        }
        for (const source of sources) {
          visited.add(source.path);
          if (Date.now() >= deadline) break;
          writeJson(cursorPath, { path: source.path });
          if (!authorizedNativePath(source.agent, source.path)) {
            for (const { job } of jobs)
              if (job.source.path === source.path) attempted.add(job.token);
            continue;
          }
          const matchingJobs = jobs
            .filter(
              (j) =>
                j.job.source.path === source.path &&
                !attempted.has(j.job.token),
            )
            .sort((a, b) => a.job.observed_size - b.job.observed_size);
          for (const matching of matchingJobs.length
            ? matchingJobs.slice(0, 1)
            : [undefined]) {
            if (matching) attempted.add(matching.job.token);
            try {
              let priorOffset = -1;
              let finalManifest;
              let complete = false;
              let synced;
              let uploadDeferred = false;
              while (Date.now() < deadline) {
                const m = await captureSource(root, folder, source, {
                  maxBytes: 16 * 1024 * 1024,
                  endOffset: matching?.job.observed_size || undefined,
                  verifyPrefix:
                    priorOffset < 0 && matching?.job.event !== "PostToolUse",
                  progress: matching?.job.event === "PostToolUse",
                  finalizeJournal: matching?.job.event === "Stop",
                  end:
                    matching?.job.event === "SessionEnd" ||
                    matching?.job.event === "SubagentStop",
                });
                for (const child of discoverClaudeChildren(source))
                  await registerSource(root, child);
                finalManifest = m;
                complete =
                  (matching?.job.observed_size
                    ? (m.coverage?.captured_through || 0) >=
                      matching.job.observed_size
                    : m.coverage?.pending_bytes === 0) &&
                  !m.gaps.some((g) => g.code === "source_unreadable");
                // Publish each immutable checkpoint. A growing native transcript
                // may never fit in one worker budget, but its captured prefix
                // must still become visible remotely before the next hook.
                if (!uploadDeferred) {
                  try {
                    synced = await syncEvidence(
                      root,
                      folder,
                      source,
                      m,
                      force,
                      deadline,
                    );
                  } catch {
                    // Upload state already records its retry policy. Keep
                    // preserving local bytes even while the API is offline.
                    uploadDeferred = true;
                  }
                }
                if (
                  complete ||
                  (m.coverage?.captured_through ?? -1) === priorOffset ||
                  m.gaps.some((g) => g.code === "source_unreadable") ||
                  synced?.blocked ||
                  matching?.job.event === "PostToolUse"
                )
                  break;
                priorOffset = m.coverage?.captured_through ?? -1;
              }
              if (
                !complete &&
                finalManifest &&
                matching &&
                !uploadDeferred &&
                !synced?.blocked
              )
                incompleteCapture = true;
              if (
                complete &&
                finalManifest &&
                matching &&
                synced?.manifest_hash === hash(JSON.stringify(finalManifest)) &&
                readJson<Job | null>(matching.path, null)?.token ===
                  matching.job.token
              )
                rmSync(matching.path, { force: true });
            } catch (error) {
              const code =
                error instanceof Error &&
                /^evidence_[a-z0-9_]+$/.test(error.message)
                  ? error.message
                  : "capture_failed";
              writeJson(
                join(
                  state,
                  "errors",
                  hash(JSON.stringify([source.agent, source.session])) +
                    ".json",
                ),
                { code, at: new Date().toISOString() },
              );
            }
          }
        }
      }
    },
    force ? 5000 : 50,
  );
  // Check after releasing ownership: a hook can enqueue between the final scan
  // and unlock while its own worker loses the lock race. Only unseen tokens
  // trigger a handoff; failed/offline jobs already attempted do not spin.
  const unseen = readdirSync(pending)
    .filter((name) => name.endsWith(".json"))
    .some((name) => {
      const job = readJson<Job | null>(join(pending, name), null);
      return job && !attempted.has(job.token);
    });
  if (unseen) (options.scheduleRetry || spawnEvidenceWorker)(root, Date.now());
  else if (readdirSync(pending).some((name) => name.endsWith(".json"))) {
    const retryTimes = sourcesInRepo(root)
      .map((source) =>
        readJson<{ blocked?: string; retry_at?: number }>(
          join(sessionDir(root, source), ".sync.json"),
          {},
        ),
      )
      .filter(
        (sync) =>
          sync.retry_at &&
          ["retry_pending", "backend_unsupported"].includes(sync.blocked || ""),
      )
      .map((sync) => sync.retry_at!);
    if (incompleteCapture) retryTimes.push(Date.now() + 1000);
    if (retryTimes.length)
      (options.scheduleRetry || spawnEvidenceWorker)(
        root,
        Math.min(...retryTimes),
      );
  }
}
export async function evidenceSync(): Promise<void> {
  const root = repoRoot(process.cwd());
  if (!root || !bound(root))
    throw new Error("Run evidence-sync in an initialized repository");
  await evidenceWorker(root, true);
  console.log(JSON.stringify(evidenceStatus(root), null, 2));
}
export function evidenceStatus(root: string): Record<string, unknown> {
  root = repoRoot(root) || root;
  const sources = sourcesInRepo(root);
  return {
    enabled: evidenceEnabled(root),
    hook_capabilities: evidenceHookCapabilities(root),
    sessions: sources.map((source) => {
      const m = readManifest(root, source),
        sync = readJson<Record<string, unknown>>(
          join(sessionDir(root, source), ".sync.json"),
          {},
        );
      return {
        agent: source.agent,
        native_session_id: source.session,
        parent_session_id: source.parent,
        revision: m?.revision || 0,
        captured_bytes: m?.objects.reduce((n, o) => n + o.byte_length, 0) || 0,
        pending_capture_bytes: m?.coverage?.pending_bytes || 0,
        last_captured_position: m?.coverage?.captured_through || 0,
        acknowledged_objects: Array.isArray(sync.acknowledged)
          ? sync.acknowledged.length
          : 0,
        gaps: m?.gaps || [],
        remote_revision: sync.revision || 0,
        blocked: sync.blocked || null,
        retry_at: sync.retry_at || null,
      };
    }),
  };
}
export function evidenceConfigure(enabled: boolean): void {
  const root = repoRoot(process.cwd());
  if (!root || !bound(root))
    throw new Error("Run evidence-status in an initialized repository");
  setEvidenceEnabled(root, enabled);
}
