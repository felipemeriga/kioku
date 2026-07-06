import { supabase } from "./supabase";

/**
 * Structured API error. Every failing apiFetch throws one of these so callers
 * can render a proper message ('userMessage') plus decide whether to retry
 * based on 'status'. .toString() also returns userMessage so `String(e)`
 * still produces something useful in legacy call sites.
 */
export class ApiError extends Error {
  status: number;
  detail: unknown;
  isNetwork: boolean;
  userMessage: string;

  constructor(opts: {
    status: number;
    detail?: unknown;
    userMessage: string;
    isNetwork?: boolean;
  }) {
    super(opts.userMessage);
    this.name = "ApiError";
    this.status = opts.status;
    this.detail = opts.detail;
    this.isNetwork = opts.isNetwork ?? false;
    this.userMessage = opts.userMessage;
  }

  toString() {
    return this.userMessage;
  }
}

// Convert whatever FastAPI put in `detail` (string, list of pydantic issues,
// or a nested object) into a single human-readable line.
function normalizeDetail(detail: unknown): string {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422 shape: [{loc: [...], msg: "...", type: "..."}]
    return detail
      .map((d: unknown) => {
        if (typeof d === "string") return d;
        if (d && typeof d === "object" && "msg" in d) {
          const m = (d as { msg?: unknown; loc?: unknown[] });
          const loc =
            Array.isArray(m.loc) && m.loc.length > 0
              ? `${m.loc.filter((x) => x !== "body").join(".")}: `
              : "";
          return `${loc}${String(m.msg)}`;
        }
        return JSON.stringify(d);
      })
      .join("; ");
  }
  if (typeof detail === "object") return JSON.stringify(detail);
  return String(detail);
}

function friendlyForStatus(status: number, detail: string): string {
  if (detail) return detail;
  if (status === 0) return "Network error — could not reach the server.";
  if (status === 401) return "Your session expired. Please sign in again.";
  if (status === 403) return "You don't have permission to do that.";
  if (status === 404) return "Not found.";
  if (status === 409) return "That conflicts with existing data.";
  if (status === 413) return "That file is too large.";
  if (status === 422) return "The request was invalid.";
  if (status === 429) return "Too many requests — try again shortly.";
  if (status >= 500) return "The server hit an error. Please try again.";
  return `Request failed (${status}).`;
}

export async function getAuthHeaders(): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) {
    throw new ApiError({
      status: 401,
      userMessage: "You're not signed in.",
    });
  }
  return {
    Authorization: `Bearer ${session.access_token}`,
    "Content-Type": "application/json",
  };
}

// One global place to react to 401s: sign the user out so ProtectedRoute
// bounces them to /login instead of leaving them stuck with a broken session.
async function handleAuthExpiry() {
  try {
    await supabase.auth.signOut();
  } catch {
    /* ignore */
  }
}

export async function apiFetch(path: string, options: RequestInit = {}) {
  let response: Response;
  try {
    const headers = await getAuthHeaders();
    response = await fetch(path, {
      ...options,
      headers: { ...headers, ...(options.headers as Record<string, string>) },
    });
  } catch (err) {
    if (err instanceof ApiError) throw err;
    // TypeError from fetch = DNS/network/CORS. Distinguish from HTTP errors.
    throw new ApiError({
      status: 0,
      isNetwork: true,
      userMessage:
        "Network error — check your connection and try again.",
      detail: err instanceof Error ? err.message : String(err),
    });
  }

  if (!response.ok) {
    // Try to read the body. FastAPI returns JSON {detail: ...}, but a 500
    // from an unhandled exception is text/plain.
    let detail: unknown = undefined;
    let detailStr = "";
    const contentType = response.headers.get("content-type") || "";
    try {
      if (contentType.includes("application/json")) {
        const body = await response.json();
        detail = (body as { detail?: unknown })?.detail ?? body;
      } else {
        const text = await response.text();
        detail = text;
      }
      detailStr = normalizeDetail(detail);
    } catch {
      /* body already consumed or malformed — leave detailStr empty */
    }

    if (response.status === 401) {
      void handleAuthExpiry();
    }

    throw new ApiError({
      status: response.status,
      detail,
      userMessage: friendlyForStatus(response.status, detailStr),
    });
  }
  return response;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export async function fetchConversations(): Promise<Conversation[]> {
  const res = await apiFetch("/api/conversations");
  return res.json();
}

export async function createConversation(): Promise<Conversation> {
  const res = await apiFetch("/api/conversations", { method: "POST" });
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  await apiFetch(`/api/conversations/${id}`, { method: "DELETE" });
}

// ── Briefing (Phase 3+) ──────────────────────────────────────────────────

export type BriefingSectionStatus = "auto" | "pinned" | "hybrid";
export type BriefingProvenance = "auto" | "user_ui" | "agent_mcp";

export interface BriefingSection<C = unknown> {
  status: BriefingSectionStatus;
  content: C;
  provenance: BriefingProvenance;
  updated_at: string;
  updated_by: string | null;
}

/** Fixed section keys — order matters for stable rendering. */
export const BRIEFING_SECTIONS = [
  "overview",
  "architecture",
  "preferences",
  "important_files",
  "how_it_runs",
  "deployment",
  "dependencies",
  "activity",
] as const;
export type BriefingSectionKey = (typeof BRIEFING_SECTIONS)[number];

export interface BriefingResponse {
  folder: { id: string; name: string; kind?: "folder" | "repo" };
  schema_version: number;
  sections: Record<BriefingSectionKey, BriefingSection>;
  last_generated_at: string | null;
}

export async function fetchBriefing(folderId: string): Promise<BriefingResponse> {
  const res = await apiFetch(`/api/folders/${folderId}/briefing`);
  return res.json();
}

export async function updateBriefingSection(
  folderId: string,
  section: BriefingSectionKey,
  content: unknown,
  status: BriefingSectionStatus = "pinned",
  updatedBy?: string,
): Promise<{ ok: boolean; section: BriefingSection }> {
  const res = await apiFetch(`/api/folders/${folderId}/briefing/section/${section}`, {
    method: "PATCH",
    body: JSON.stringify({ content, status, updated_by: updatedBy }),
  });
  return res.json();
}

export async function resetBriefingSection(
  folderId: string,
  section: BriefingSectionKey,
): Promise<{ ok: boolean; section: BriefingSection }> {
  const res = await apiFetch(`/api/folders/${folderId}/briefing/section/${section}/reset`, {
    method: "POST",
  });
  return res.json();
}

export async function renameConversation(
  id: string,
  title: string
): Promise<Conversation> {
  const res = await apiFetch(`/api/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  return res.json();
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

export async function fetchConversation(
  id: string
): Promise<ConversationWithMessages> {
  const res = await apiFetch(`/api/conversations/${id}`);
  return res.json();
}

export interface ChatFilters {
  topic?: string;
  keyword?: string;
}

export type ChatStage = "searching" | "analyzing" | "generating";

export interface StageEvent {
  stage: ChatStage;
  docs?: number;
}

export interface DocumentFilters {
  topics: string[];
  keywords: string[];
}

export async function fetchDocumentFilters(): Promise<DocumentFilters> {
  const res = await apiFetch("/api/documents/filters");
  return res.json();
}

export async function streamChat(
  conversationId: string,
  content: string,
  onToken: (token: string) => void,
  onDone: () => void,
  filters?: ChatFilters,
  onStage?: (event: StageEvent) => void,
  fastMode?: boolean,
  onError?: (err: ApiError) => void,
): Promise<void> {
  // A stream is "clean" only if it emits a data.done frame. Anything else —
  // TCP drop, backend timeout, JSON parse loss — should raise, not silently
  // close (which is how the previous code let broken responses pretend they
  // finished successfully).
  let headers: Record<string, string>;
  try {
    headers = await getAuthHeaders();
  } catch (err) {
    const e = err instanceof ApiError ? err : new ApiError({
      status: 401, userMessage: "You're not signed in.",
    });
    onError?.(e);
    throw e;
  }

  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers,
      body: JSON.stringify({
        conversation_id: conversationId,
        content,
        topic: filters?.topic || null,
        keyword: filters?.keyword || null,
        fast_mode: fastMode ?? false,
      }),
    });
  } catch (err) {
    const e = new ApiError({
      status: 0, isNetwork: true,
      userMessage: "Network error — the chat request never reached the server.",
      detail: err instanceof Error ? err.message : String(err),
    });
    onError?.(e);
    throw e;
  }

  if (!response.ok) {
    let detailStr = "";
    try {
      const body = await response.json();
      detailStr = normalizeDetail((body as { detail?: unknown })?.detail ?? body);
    } catch { /* non-JSON body */ }
    if (response.status === 401) void handleAuthExpiry();
    const e = new ApiError({
      status: response.status,
      userMessage: friendlyForStatus(response.status, detailStr),
    });
    onError?.(e);
    throw e;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    const e = new ApiError({
      status: 500, userMessage: "The server returned an empty chat response.",
    });
    onError?.(e);
    throw e;
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let sawDone = false;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          let data: any;
          try {
            data = JSON.parse(line.slice(6));
          } catch {
            continue;
          }
          if (data.error) {
            const e = new ApiError({
              status: 500,
              userMessage: normalizeDetail(data.error) || "The model returned an error mid-response.",
            });
            onError?.(e);
            throw e;
          }
          if (data.done) {
            sawDone = true;
            onDone();
            return;
          }
          if (data.stage && onStage) {
            onStage({ stage: data.stage, docs: data.docs });
          }
          if (data.token) {
            onToken(data.token);
          }
        }
      }
    }
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const e = new ApiError({
      status: 0, isNetwork: true,
      userMessage: "The chat connection dropped before the answer finished.",
      detail: err instanceof Error ? err.message : String(err),
    });
    onError?.(e);
    throw e;
  }

  // Stream closed cleanly BUT with no data.done — treat as a truncated response.
  if (!sawDone) {
    const e = new ApiError({
      status: 0, isNetwork: true,
      userMessage: "The response ended before the answer was complete.",
    });
    onError?.(e);
    throw e;
  }
  onDone();
}

export interface DocumentInfo {
  source_filename: string;
  source_type: string;
  has_file: boolean;
  chunks: number;
  status: "processing" | "completed" | "failed";
  created_at: string;
  folder_id: string | null;
}

export interface UploadResult {
  task_id: string;
}

export type IngestionStage =
  | "uploading"
  | "parsing"
  | "chunking"
  | "extracting_metadata"
  | "embedding"
  | "storing"
  | "completed"
  | "error"
  | "duplicate";

export interface IngestionTask {
  id: string;
  user_id: string;
  filename: string;
  folder_id: string | null;
  stage: IngestionStage;
  stage_detail: string | null;
  error_message: string | null;
  chunks_total: number | null;
  chunks_done: number;
  duplicate: boolean;
  document_ids: string[];
  created_at: string;
  updated_at: string;
}

export async function fetchDocuments(
  folderId?: string | null
): Promise<DocumentInfo[]> {
  const params = folderId ? `?folder_id=${folderId}` : "";
  const res = await apiFetch(`/api/documents${params}`);
  return res.json();
}

export async function uploadDocument(
  file: File,
  folderId?: string | null
): Promise<UploadResult> {
  const { Authorization } = await getAuthHeaders();
  const formData = new FormData();
  formData.append("file", file);

  const params = folderId ? `?folder_id=${folderId}` : "";
  let response: Response;
  try {
    response = await fetch(`/api/documents/upload${params}`, {
      method: "POST",
      headers: { Authorization },
      body: formData,
    });
  } catch (err) {
    throw new ApiError({
      status: 0, isNetwork: true,
      userMessage: `Network error while uploading “${file.name}”.`,
      detail: err instanceof Error ? err.message : String(err),
    });
  }

  if (!response.ok) {
    let detailStr = "";
    try {
      const body = await response.json();
      detailStr = normalizeDetail((body as { detail?: unknown })?.detail ?? body);
    } catch { /* non-JSON */ }
    if (response.status === 401) void handleAuthExpiry();
    throw new ApiError({
      status: response.status,
      userMessage: friendlyForStatus(
        response.status,
        detailStr || `Upload failed for “${file.name}”.`,
      ),
    });
  }
  return response.json();
}

export async function moveDocument(
  filename: string,
  folderId: string | null
): Promise<void> {
  await apiFetch(`/api/documents/${encodeURIComponent(filename)}/move`, {
    method: "PATCH",
    body: JSON.stringify({ folder_id: folderId }),
  });
}

export async function deleteDocument(filename: string): Promise<void> {
  await apiFetch(`/api/documents/${encodeURIComponent(filename)}`, {
    method: "DELETE",
  });
}

export async function downloadDocument(filename: string): Promise<string> {
  const res = await apiFetch(
    `/api/documents/${encodeURIComponent(filename)}/download`
  );
  const data = await res.json();
  return data.url;
}

export async function fetchIngestionStatus(): Promise<IngestionTask[]> {
  const res = await apiFetch("/api/documents/ingestion-status");
  return res.json();
}

// --- Folders ---

export interface Folder {
  id: string;
  name: string;
  parent_id: string | null;
  user_id: string;
  created_at: string;
  /** Phase 1 of the second-brain reframe. 'repo' folders are bound to a
   *  GitHub sync config and hold the strict 8-section briefing; 'folder'
   *  is anything else. Server may omit before the migration lands — treat
   *  missing as 'folder'. */
  kind?: "folder" | "repo";
}

export interface Breadcrumb {
  id: string;
  name: string;
}

export async function fetchFolders(
  parentId?: string | null
): Promise<Folder[]> {
  const params = parentId ? `?parent_id=${parentId}` : "";
  const res = await apiFetch(`/api/folders${params}`);
  return res.json();
}

export async function createFolder(
  name: string,
  parentId?: string | null
): Promise<Folder> {
  const res = await apiFetch("/api/folders", {
    method: "POST",
    body: JSON.stringify({ name, parent_id: parentId || null }),
  });
  return res.json();
}

export async function renameFolder(
  folderId: string,
  name: string
): Promise<Folder> {
  const res = await apiFetch(`/api/folders/${folderId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
  return res.json();
}

export async function deleteFolder(
  folderId: string,
  deleteDocs: boolean = false
): Promise<void> {
  const q = deleteDocs ? "?delete_docs=true" : "";
  await apiFetch(`/api/folders/${folderId}${q}`, { method: "DELETE" });
}

export async function fetchBreadcrumbs(
  folderId: string
): Promise<Breadcrumb[]> {
  const res = await apiFetch(`/api/folders/${folderId}/breadcrumbs`);
  return res.json();
}

// --- Folder Summaries ---

export interface FolderSummaryContent {
  title: string;
  purpose: string;
  overview: string;
  themes: { name: string; description: string }[];
  key_documents: { filename: string; role: string }[];
  key_facts: string[];
  entities: string[];
  gotchas: string[];
}

export interface FolderSummaryRow {
  id: string;
  folder_id: string;
  generated_at: string;
  /** 'workspace_rollup' is used for container folders whose summary is
   *  synthesized from direct-child summaries rather than doc summaries. */
  kind: "full" | "delta" | "seed" | "workspace_rollup";
  trigger: string | null;
  content: FolderSummaryContent;
  previous_content: FolderSummaryContent | null;
  changed_files: {
    added?: string[];
    removed?: string[];
    modified?: string[];
    subfolder_count?: number;
    subfolder_snapshots?: Record<string, string>;
  };
  doc_count: number;
  input_tokens: number | null;
  output_tokens: number | null;
  duration_ms: number | null;
}

export interface WorkspaceSubfolderCard {
  id: string;
  name: string;
  purpose: string;
  overview: string;
  key_facts: string[];
  doc_count: number;
  has_mem0: boolean;
  has_github: boolean;
  has_notion: boolean;
  has_summary: boolean;
}

export interface FolderSummaryResponse {
  folder: { id: string; name: string; parent_id: string | null };
  summary: FolderSummaryRow | null;
  /** Populated only when summary.kind === 'workspace_rollup'. Direct
   *  subfolder cards for the workspace grid. */
  subfolders: WorkspaceSubfolderCard[] | null;
}

export interface FolderSummaryHistoryRow {
  id: string;
  generated_at: string;
  kind: "full" | "delta" | "seed" | "workspace_rollup";
  trigger: string | null;
  doc_count: number;
  changed_files: { added: string[]; removed: string[]; modified: string[] };
  input_tokens: number | null;
  output_tokens: number | null;
  duration_ms: number | null;
}

export async function fetchFolderSummary(
  folderId: string
): Promise<FolderSummaryResponse> {
  const res = await apiFetch(`/api/folders/${folderId}/summary`);
  return res.json();
}

export async function fetchFolderSummaryHistory(
  folderId: string,
  limit = 10
): Promise<FolderSummaryHistoryRow[]> {
  const res = await apiFetch(
    `/api/folders/${folderId}/summary/history?limit=${limit}`
  );
  return res.json();
}

export async function regenerateFolderSummary(
  folderId: string,
  force = false
): Promise<{ ok: boolean; job_id: string | null; force: boolean }> {
  const res = await apiFetch(`/api/folders/${folderId}/summary/regenerate`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
  return res.json();
}

// --- API Keys ---

export interface ApiKeyInfo {
  id: string;
  name: string;
  scope_folder_id: string;
  scope_folder_name: string;
  created_at: string;
}

export interface CreatedApiKey {
  key: string;
  id: string;
  name: string;
  scope_folder_id: string;
  scope_folder_name: string;
  created_at: string;
}

export async function fetchApiKeys(): Promise<ApiKeyInfo[]> {
  const res = await apiFetch("/api/api-keys");
  return res.json();
}

export async function createApiKey(
  name: string,
  scopeFolderId: string
): Promise<CreatedApiKey> {
  const res = await apiFetch("/api/api-keys", {
    method: "POST",
    body: JSON.stringify({ name, scope_folder_id: scopeFolderId }),
  });
  return res.json();
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await apiFetch(`/api/api-keys/${keyId}`, { method: "DELETE" });
}

// --- Scopes (root folders) ---

export async function fetchRootFolders(): Promise<Folder[]> {
  return fetchFolders(null);
}

// --- Notion Sync ---

export interface NotionConfig {
  id: string;
  root_folder_id: string;
  notion_page_id: string;
  notion_page_title: string | null;
  fast_poll_interval_min: number;
  last_fast_sync_at: string | null;
  last_full_sync_at: string | null;
  last_error: string | null;
}

export interface NotionPageOption {
  id: string;
  title: string;
}

export interface IngestionJob {
  id: string;
  user_id: string;
  kind: "upload" | "drop" | "notion_sync" | "notion_page";
  source_ref: string;
  parent_job_id: string | null;
  root_folder_id: string | null;
  status: "queued" | "running" | "completed" | "failed";
  current_step: string | null;
  total_batches: number;
  processed_batches: number;
  total_pages: number | null;
  processed_pages: number | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface SyncNowResponse {
  job_id: string;
  already_running: boolean;
}

export async function fetchIngestionJob(jobId: string): Promise<IngestionJob> {
  const res = await apiFetch(`/api/ingestion-jobs/${jobId}`);
  return res.json();
}

export async function fetchActiveIngestionJobs(): Promise<IngestionJob[]> {
  const res = await apiFetch("/api/ingestion-jobs");
  return res.json();
}

export async function fetchNotionConfigs(): Promise<NotionConfig[]> {
  const res = await apiFetch("/api/notion/configs");
  return res.json();
}

export async function connectNotion(input: {
  root_folder_id: string;
  notion_page_id: string;
  notion_page_title: string;
  integration_token: string;
  fast_poll_interval_min?: number;
}): Promise<NotionConfig> {
  const res = await apiFetch("/api/notion/configs", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return res.json();
}

export async function disconnectNotion(
  configId: string,
  deleteDocs: boolean
): Promise<void> {
  await apiFetch(
    `/api/notion/configs/${configId}?delete_docs=${deleteDocs}`,
    { method: "DELETE" }
  );
}

export async function syncNotionNow(
  configId: string
): Promise<SyncNowResponse> {
  const res = await apiFetch(`/api/notion/configs/${configId}/sync`, {
    method: "POST",
  });
  return res.json();
}

export async function reconcileNotionNow(
  configId: string
): Promise<SyncNowResponse> {
  const res = await apiFetch(`/api/notion/configs/${configId}/reconcile`, {
    method: "POST",
  });
  return res.json();
}

export async function listNotionPages(
  integrationToken: string,
  query: string
): Promise<NotionPageOption[]> {
  const params = new URLSearchParams({
    integration_token: integrationToken,
    query,
  });
  const res = await apiFetch(`/api/notion/pages?${params.toString()}`);
  return res.json();
}

// --- Mem0 integration ---

export interface Mem0Config {
  id: string;
  root_folder_id: string;
  root_folder_name: string;
  org_id: string | null;
  project_id: string | null;
  last_verified_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export async function fetchMem0Configs(): Promise<Mem0Config[]> {
  const res = await apiFetch("/api/mem0/configs");
  return res.json();
}

export async function connectMem0(input: {
  root_folder_id: string;
  api_key: string;
  org_id?: string;
  project_id?: string;
}): Promise<Mem0Config> {
  const res = await apiFetch("/api/mem0/connect", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return res.json();
}

export async function disconnectMem0(configId: string): Promise<void> {
  await apiFetch(`/api/mem0/configs/${configId}`, { method: "DELETE" });
}

export async function verifyMem0(
  configId: string
): Promise<{ ok: boolean; error: string | null }> {
  const res = await apiFetch(`/api/mem0/configs/${configId}/verify`, {
    method: "POST",
  });
  return res.json();
}

export type MemoryScope = "eternal" | "episodic";
export type MemoryCategory =
  | "decision"
  | "finding"
  | "issue"
  | "preference"
  | "session"
  | "note";

export interface MemoryRecord {
  id: string;
  content: string;
  scope: MemoryScope | null;
  category: MemoryCategory | null;
  tags: string[];
  written_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export async function listFolderMemories(
  configId: string,
  opts: { scope?: "any" | MemoryScope; limit?: number } = {}
): Promise<{ folder_id: string; memories: MemoryRecord[] }> {
  const params = new URLSearchParams({
    scope: opts.scope ?? "any",
    limit: String(opts.limit ?? 200),
  });
  const res = await apiFetch(
    `/api/mem0/configs/${configId}/memories?${params.toString()}`
  );
  return res.json();
}

export async function deleteFolderMemory(
  configId: string,
  memoryId: string
): Promise<void> {
  await apiFetch(`/api/mem0/configs/${configId}/memories/${memoryId}`, {
    method: "DELETE",
  });
}

export async function addFolderMemory(input: {
  root_folder_id: string;
  content: string;
  category: MemoryCategory;
  scope?: MemoryScope;
  tags?: string[];
  written_by?: string;
}): Promise<{
  ok: boolean;
  duplicate?: boolean;
  existing_id?: string;
  metadata: Record<string, unknown>;
}> {
  const res = await apiFetch("/api/mem0/memories", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return res.json();
}

export type ViewableAs =
  | "markdown"
  | "image"
  | "pdf"
  | "audio"
  | "video"
  | "code"
  | "text";

export interface DocumentContent {
  source_filename: string;
  source_type: string | null;
  metadata: Record<string, unknown>;
  chunk_count: number;
  folder_id: string | null;
  status: string | null;
  created_at: string | null;
  content: string;
  viewable_as: ViewableAs;
  /** Short-lived signed URL (15 min) to view the original file inline. */
  file_url: string | null;
  bucket: string | null;
}

export async function fetchDocumentContent(
  filename: string,
  folderId?: string
): Promise<DocumentContent> {
  const params = folderId ? `?folder_id=${folderId}` : "";
  const res = await apiFetch(
    `/api/documents/${encodeURIComponent(filename)}/content${params}`
  );
  return res.json();
}

// --- GitHub integration ---

export interface GitHubConfig {
  id: string;
  root_folder_id: string;
  root_folder_name: string;
  repo_owner: string;
  repo_name: string;
  since_days: number;
  has_token: boolean;
  last_synced_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export async function fetchGitHubConfigs(): Promise<GitHubConfig[]> {
  const res = await apiFetch("/api/github/configs");
  return res.json();
}

export async function connectGitHub(input: {
  root_folder_id: string;
  repo_url: string;
  token?: string;
  since_days?: number;
}): Promise<GitHubConfig> {
  const res = await apiFetch("/api/github/connect", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return res.json();
}

export async function disconnectGitHub(
  configId: string,
  deleteDocs = false
): Promise<void> {
  await apiFetch(
    `/api/github/configs/${configId}?delete_docs=${deleteDocs}`,
    { method: "DELETE" }
  );
}

export async function syncGitHubNow(
  configId: string
): Promise<{ ok: boolean; job_id: string | null }> {
  const res = await apiFetch(`/api/github/configs/${configId}/sync`, {
    method: "POST",
  });
  return res.json();
}

export interface GitHubRepoOption {
  owner: string;
  name: string;
  full_name: string;
  private: boolean;
  description: string;
  pushed_at: string | null;
  url: string | null;
}

export async function listGitHubRepos(
  token: string
): Promise<GitHubRepoOption[]> {
  const res = await apiFetch("/api/github/repos", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
  return res.json();
}
