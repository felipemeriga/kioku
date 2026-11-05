import { ApiError, apiFetch } from "./api";

export function evidenceRetry(failures: number, error: Error) {
  return (
    failures < 1 &&
    !(
      error instanceof ApiError &&
      [400, 401, 403, 404, 409, 410, 413, 422].includes(error.status)
    )
  );
}

export type EvidenceGap = { code: string; message?: string; event_id?: string };
export type EvidenceChild = {
  id: string;
  agent: string;
  native_session_id: string;
  event_count: number;
};
export interface EvidenceSession extends EvidenceChild {
  parent_session_id: string | null;
  root_session_id: string;
  title?: string | null;
  summary?: string | null;
  first_event_at: string | null;
  last_event_at: string | null;
  manifest_revision: number;
  indexed_revision: number;
  capture_status: string;
  index_status: string;
  active_day_count?: number;
  children: EvidenceChild[];
  gaps: EvidenceGap[];
}
export interface EvidenceSource {
  object_id: string;
  stream_id: string;
  generation: number;
  record_sequence: number;
}
export interface EvidenceAttachment {
  id: string;
  original_name: string;
  byte_length: number;
  content_type?: string;
  source_event_id?: string;
  available: boolean;
  sha256?: string;
}
export interface EvidencePresentation {
  version: 1;
  blocks: Array<{
    kind: "markdown" | "code" | "terminal" | "json" | "text";
    text: string;
    language?: string;
    viewer_truncated?: boolean;
  }>;
  tool?: {
    name?: string;
    command_text?: string;
    call_id?: string;
    cwd?: string;
    exit_code?: number;
    duration_seconds?: number;
    orchestration_seconds?: number;
    status?: string;
  };
  viewer_truncated: boolean;
  source_truncated: boolean;
}
export interface EvidenceEvent {
  event_id: string;
  role: string;
  event_type: string;
  event_at: string | null;
  content_preview: string;
  turn_id?: string | null;
  call_id?: string | null;
  raw_available: boolean;
  viewer_truncated: boolean;
  source_truncated: boolean;
  child_session_id?: string | null;
  inherited?: boolean;
  attachments: EvidenceAttachment[];
  source: EvidenceSource;
  presentation?: EvidencePresentation;
}
export interface RawEvidenceRecord {
  event_id: string;
  source: EvidenceSource;
  byte_length: number;
  sha256: string;
  raw_text: string | null;
  raw_encoding: "utf-8" | "base64";
  viewer_truncated: boolean;
}
export interface EvidenceWindow {
  events: EvidenceEvent[];
  records: RawEvidenceRecord[];
  previous_cursor: string | null;
  next_cursor: string | null;
  snapshot_revision: number | null;
  status: string;
}
export interface EvidenceLocation {
  folderId: string;
  sessionId: string;
  eventId?: string;
  endEventId?: string;
  date?: string;
  timezone: string;
  mode: "conversation" | "raw";
  approximate?: boolean;
}
export interface EvidenceWindowOptions {
  around?: string;
  date?: string;
  timezone: string;
  before?: string;
  after?: string;
  snapshot_revision?: number | null;
  limit?: number;
}
export interface JournalEvidenceLink {
  status: "available" | "pending" | "absent" | "deleted" | "approximate";
  session_id?: string;
  start_event_id?: string;
  end_event_id?: string;
}

const segment = encodeURIComponent;
const prefix = (folder: string) =>
  `/api/folders/${segment(folder)}/agent-sessions`;
const sessionPath = (folder: string, session: string) =>
  `${prefix(folder)}/${segment(session)}`;
function query(values: Record<string, string | number | null | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  return params.size ? `?${params}` : "";
}

export const evidenceKeys = {
  sessions: (folder: string, cursor?: string) =>
    ["agent-evidence-sessions", folder, cursor ?? ""] as const,
  session: (folder: string, session: string) =>
    ["agent-evidence-session", folder, session] as const,
  days: (folder: string, session: string, timezone: string) =>
    ["agent-evidence-days", folder, session, timezone] as const,
  window: (location: EvidenceLocation) =>
    [
      "agent-evidence-window",
      location.folderId,
      location.sessionId,
      location.mode,
      location.eventId ?? "",
      location.date ?? "",
      location.timezone,
    ] as const,
  entry: (folder: string, entry: string) =>
    ["agent-evidence-entry", folder, entry] as const,
};

export async function listEvidenceSessions(
  folder: string,
  cursor?: string,
  signal?: AbortSignal,
) {
  const response = await apiFetch(
    `${prefix(folder)}${query({ cursor, limit: 50 })}`,
    { signal },
  );
  return response.json() as Promise<{
    sessions: EvidenceSession[];
    next_cursor?: string | null;
  }>;
}
export async function getEvidenceSession(
  folder: string,
  session: string,
  signal?: AbortSignal,
) {
  const response = await apiFetch(sessionPath(folder, session), { signal });
  return response.json() as Promise<EvidenceSession>;
}
export async function getEvidenceDays(
  folder: string,
  session: string,
  timezone: string,
  signal?: AbortSignal,
) {
  const response = await apiFetch(
    `${sessionPath(folder, session)}/days${query({ timezone })}`,
    { signal },
  );
  return response.json() as Promise<{
    days: {
      date: string;
      event_count: number;
      turn_count: number;
      first_event_id: string;
    }[];
    timezone: string;
  }>;
}
export async function getEvidenceWindow(
  location: EvidenceLocation,
  options: EvidenceWindowOptions,
  signal?: AbortSignal,
): Promise<EvidenceWindow> {
  const route = location.mode === "raw" ? "raw-records" : "events";
  const response = await apiFetch(
    `${sessionPath(location.folderId, location.sessionId)}/${route}${query({
      ...options,
      limit: options.limit ?? 50,
    })}`,
    { signal },
  );
  const body = (await response.json()) as Partial<EvidenceWindow>;
  return {
    events: [],
    records: [],
    previous_cursor: null,
    next_cursor: null,
    snapshot_revision: null,
    status: response.status === 202 ? "processing" : "ok",
    ...body,
  };
}
export async function getJournalEvidence(
  folder: string,
  entry: string,
  signal?: AbortSignal,
) {
  const response = await apiFetch(
    `${prefix(folder)}/evidence-for-entry/${segment(entry)}`,
    { signal },
  );
  return response.json() as Promise<JournalEvidenceLink>;
}
export async function getEvidenceContent(
  location: EvidenceLocation,
  event: string,
  offset = 0,
  signal?: AbortSignal,
) {
  const response = await apiFetch(
    `${sessionPath(location.folderId, location.sessionId)}/events/${segment(
      event,
    )}/content${query({ offset, limit_bytes: 65536 })}`,
    { signal },
  );
  return response.json() as Promise<{
    event_id: string;
    content: string;
    byte_length: number;
    viewer_truncated: boolean;
    has_more: boolean;
    next_offset?: number;
    presentation?: EvidencePresentation;
  }>;
}
export async function getAttachmentMetadata(
  location: EvidenceLocation,
  attachment: string,
  signal?: AbortSignal,
) {
  const response = await apiFetch(
    `${sessionPath(
      location.folderId,
      location.sessionId,
    )}/attachments/${segment(attachment)}`,
    { signal },
  );
  return response.json() as Promise<EvidenceAttachment>;
}
export async function getAttachmentPreview(
  location: EvidenceLocation,
  attachment: string,
  signal?: AbortSignal,
) {
  const response = await apiFetch(
    `${sessionPath(
      location.folderId,
      location.sessionId,
    )}/attachments/${segment(attachment)}?content=true`,
    { signal, headers: { Range: "bytes=0-65535" } },
  );
  return response.text();
}
export async function downloadEvidence(
  location: EvidenceLocation,
  kind: "raw" | "attachment",
  id: string,
) {
  const path =
    kind === "raw"
      ? `/events/${segment(id)}/raw?download=true`
      : `/attachments/${segment(id)}?download=true`;
  const response = await apiFetch(
    sessionPath(location.folderId, location.sessionId) + path,
  );
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = kind === "raw" ? `source-${id}.jsonl` : `attachment-${id}`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function evidenceUrl(location: EvidenceLocation) {
  return `/folders/${segment(location.folderId)}/agent-sessions/${segment(
    location.sessionId,
  )}${query({
    event: location.eventId,
    end: location.endEventId,
    date: location.date,
    mode: location.mode,
    tz: location.timezone,
    approx: location.approximate ? "1" : undefined,
  })}`;
}
