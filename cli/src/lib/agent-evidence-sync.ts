/** Scoped REST transport for original objects, independent of journal MCP sync. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { configDir } from "./config.js";
import { readMcpEntry } from "./claude.js";
import { mcpUrlToRestBase } from "./urls.js";
import {
  hash,
  readJson,
  sessionDir,
  withEvidenceLock,
  writeJson,
  type EvidenceManifest,
  type Source,
} from "./agent-evidence.js";

/** Four shared slots cap requests across repositories and CLI processes. */
export async function withEvidenceUploadSlot<T>(
  work: () => Promise<T>,
  deadline = Date.now() + 90_000,
): Promise<T> {
  while (Date.now() < deadline) {
    for (let slot = 0; slot < 4; slot++) {
      try {
        return await withEvidenceLock(
          join(configDir(), "evidence-upload-slots", `${slot}.lock`),
          work,
          0,
        );
      } catch (error) {
        if (!(error instanceof Error) || error.message !== "evidence_lock_busy")
          throw error;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error("evidence_upload_budget_exhausted");
}
/** Object storage can acknowledge after tens of seconds; keep control calls short. */
export function evidenceRequestTimeout(
  method: string | undefined,
  remaining: number,
): number {
  return Math.max(1, Math.min(method === "PUT" ? 120_000 : 30_000, remaining));
}
export class EvidenceHttpError extends Error {
  constructor(
    public status: number,
    public detail: Record<string, unknown>,
    public retryAfterMs = 0,
  ) {
    super(`evidence_http_${status}`);
  }
}
interface SyncState {
  revision: number;
  session_id?: string;
  acknowledged: string[];
  manifest_hash?: string;
  attempts: number;
  retry_at?: number;
  blocked?: string;
  acknowledged_links?: string[];
  acknowledged_gaps?: string[];
}
export function evidenceApiBase(mcpUrl: string): string {
  if (process.env.KIOKU_API_BASE)
    return process.env.KIOKU_API_BASE.replace(/\/$/, "");
  const url = new URL(mcpUrl);
  if (url.port === "8001" || /(^|\.)mcp\./.test(url.hostname))
    return mcpUrlToRestBase(mcpUrl);
  return url.origin;
}
export async function syncEvidence(
  root: string,
  folder: string,
  source: Source,
  manifest: EvidenceManifest,
  force = false,
  deadline = Date.now() + 90_000,
): Promise<SyncState> {
  const dir = sessionDir(root, source),
    statePath = join(dir, ".sync.json");
  return withEvidenceLock(
    join(dir, ".upload.lock"),
    async () => {
      const state = readJson<SyncState>(statePath, {
        revision: 0,
        acknowledged: [],
        attempts: 0,
      });
      const signature = hash(JSON.stringify(manifest));
      if (
        state.manifest_hash === signature ||
        (!force && state.retry_at && state.retry_at > Date.now())
      )
        return state;
      const entry = readMcpEntry(root);
      if (!entry) throw new Error("evidence_configuration_missing");
      const base = evidenceApiBase(entry.entry.url) + "/api/agent-evidence";
      const request = async (
        path: string,
        init: RequestInit = {},
      ): Promise<Record<string, unknown>> => {
        for (let attempt = 0; ; attempt++) {
          try {
            return await withEvidenceUploadSlot(async () => {
              const response = await fetch(base + path, {
                ...init,
                redirect: "manual",
                signal: AbortSignal.timeout(
                  evidenceRequestTimeout(init.method, deadline - Date.now()),
                ),
                headers: {
                  Authorization: `Bearer ${entry.key}`,
                  ...init.headers,
                },
              });
              let payload: Record<string, unknown> = {};
              try {
                payload = (await response.json()) as Record<string, unknown>;
              } catch {
                /* response not JSON */
              }
              if (!response.ok) {
                const delay = response.headers.get("retry-after");
                const retryAfter = delay
                  ? Number.isFinite(Number(delay))
                    ? Number(delay) * 1000
                    : Math.max(0, Date.parse(delay) - Date.now())
                  : 0;
                throw new EvidenceHttpError(
                  response.status,
                  payload,
                  retryAfter,
                );
              }
              return payload;
            }, deadline);
          } catch (error) {
            const retryable =
              !(error instanceof EvidenceHttpError) ||
              [408, 429, 500, 502, 503, 504].includes(error.status);
            const wait = Math.max(
              error instanceof EvidenceHttpError ? error.retryAfterMs : 0,
              250 * 2 ** attempt,
            );
            if (
              !retryable ||
              attempt >= 2 ||
              Date.now() + wait + 100 >= deadline
            )
              throw error;
            await new Promise((resolve) => setTimeout(resolve, wait));
          }
        }
      };
      try {
        const capabilities = await request("/capabilities");
        if (!capabilities.enabled || capabilities.schema !== 1) {
          state.blocked = "backend_unsupported";
          state.retry_at = Date.now() + 300_000;
          writeJson(statePath, state);
          return state;
        }
        const maximum =
          Number(capabilities.max_object_bytes) || 64 * 1024 * 1024;
        const batchLimit = Math.max(
          1,
          Math.min(256, Number(capabilities.max_batch_objects) || 256),
        );
        let conflicts = 0;
        while (true) {
          if (Date.now() >= deadline) {
            state.blocked = "retry_pending";
            state.retry_at = Date.now() + 1000;
            writeJson(statePath, state);
            return state;
          }
          const outstanding = manifest.objects.filter(
            (o) => !state.acknowledged.includes(o.id),
          );
          const objects = outstanding.slice(0, batchLimit);
          if (objects.some((o) => o.byte_length > maximum)) {
            state.blocked = "blocked_size_limit";
            writeJson(statePath, state);
            return state;
          }
          const pendingLinks = manifest.journal_links.filter(
            (link) =>
              !state.acknowledged_links?.includes(hash(JSON.stringify(link))),
          );
          // The remote gap list is a current snapshot. Aggregate repetitive event
          // gaps by code; exact event evidence remains in the local manifest.
          const gapCounts = new Map<string, number>();
          for (const gap of manifest.gaps)
            gapCounts.set(gap.code, (gapCounts.get(gap.code) || 0) + 1);
          const pendingGaps = [...gapCounts].map(([code, count]) => ({
            code,
            name: `count:${count}`,
          }));
          const links =
            outstanding.length <= batchLimit ? pendingLinks.slice(0, 256) : [];
          const gaps = pendingGaps.slice(0, 256);
          const id = hash(
            JSON.stringify([
              source.agent,
              source.session,
              manifest.revision,
              state.revision,
              objects.map((o) => o.id),
              links,
              gaps,
              manifest.lifecycle,
            ]),
          );
          const descriptors = objects.map(
            ({ path: _path, oversized_record: _oversized, ...descriptor }) =>
              descriptor,
          );
          const body = {
            schema: 1,
            folder_id: folder,
            agent: source.agent,
            native_session_id: source.session,
            native_root_session_id: source.root,
            native_parent_session_id: source.parent,
            producer_id: manifest.producer_id,
            batch_id: id,
            base_revision: state.revision,
            objects: descriptors,
            journal_links: links,
            gaps,
            lifecycle: manifest.lifecycle,
          };
          try {
            const batch = await request("/batches", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            });
            const missing = (batch.missing_objects as string[]) || [];
            for (const object of objects)
              if (missing.includes(object.id)) {
                const bytes = readFileSync(join(dir, object.path));
                if (
                  bytes.length !== object.byte_length ||
                  hash(bytes) !== object.sha256
                )
                  throw new Error("evidence_local_integrity_failed");
                await request(
                  `/batches/${encodeURIComponent(id)}/objects/${encodeURIComponent(object.id)}`,
                  {
                    method: "PUT",
                    headers: { "Content-Type": "application/octet-stream" },
                    body: new Uint8Array(bytes),
                  },
                );
              }
            const result = await request(
              `/batches/${encodeURIComponent(id)}/commit`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ base_revision: state.revision }),
              },
            );
            if (result.status !== "accepted" && result.status !== "unchanged")
              throw new Error("evidence_commit_not_accepted");
            state.revision = Number(result.revision);
            state.session_id = String(result.session_id ?? batch.session_id);
            state.acknowledged = [
              ...new Set([...state.acknowledged, ...objects.map((o) => o.id)]),
            ];
            state.acknowledged_links = [
              ...new Set([
                ...(state.acknowledged_links || []),
                ...links.map((link) => hash(JSON.stringify(link))),
              ]),
            ];
            state.acknowledged_gaps = [
              ...new Set([
                ...(state.acknowledged_gaps || []),
                ...gaps.map((gap) => hash(JSON.stringify(gap))),
              ]),
            ];
            const finished =
              outstanding.length <= batchLimit &&
              pendingLinks.length <= links.length;
            state.attempts = 0;
            delete state.blocked;
            delete state.retry_at;
            if (finished) state.manifest_hash = signature;
            writeJson(statePath, state);
            if (finished) return state;
          } catch (error) {
            if (
              !(error instanceof EvidenceHttpError) ||
              error.status !== 409 ||
              conflicts++ >= 3
            )
              throw error;
            const detail =
              typeof error.detail.detail === "object"
                ? (error.detail.detail as Record<string, unknown>)
                : error.detail;
            if (detail.code === "deleted" || detail.code === "session_deleted")
              throw error;
            const current = Number(detail.current_revision ?? detail.revision);
            if (!Number.isFinite(current)) throw error;
            state.revision = current;
            writeJson(statePath, state);
          }
        }
      } catch (error) {
        state.attempts++;
        const http = error instanceof EvidenceHttpError ? error : null;
        state.blocked =
          http && [401, 403, 404, 410, 413, 422].includes(http.status)
            ? `http_${http.status}`
            : error instanceof Error &&
                error.message === "evidence_local_integrity_failed"
              ? error.message
              : "retry_pending";
        state.retry_at =
          Date.now() +
          Math.max(
            http?.retryAfterMs || 0,
            Math.min(300_000, 1000 * 2 ** Math.min(state.attempts, 8)) *
              (0.8 + Math.random() * 0.4),
          );
        writeJson(statePath, state);
        throw error;
      }
    },
    500,
  );
}
