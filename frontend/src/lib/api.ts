import { supabase } from "./supabase";

export async function getAuthHeaders(): Promise<Record<string, string>> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  return {
    Authorization: `Bearer ${session.access_token}`,
    "Content-Type": "application/json",
  };
}

export async function apiFetch(path: string, options: RequestInit = {}) {
  const headers = await getAuthHeaders();
  const response = await fetch(path, {
    ...options,
    headers: { ...headers, ...(options.headers as Record<string, string>) },
  });
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
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
  fastMode?: boolean
): Promise<void> {
  const headers = await getAuthHeaders();
  const response = await fetch("/api/chat", {
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

  if (!response.ok) {
    throw new Error(`Chat error: ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

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
        if (data.done) {
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
  const response = await fetch(`/api/documents/upload${params}`, {
    method: "POST",
    headers: { Authorization },
    body: formData,
  });
  if (!response.ok) {
    const err = await response
      .json()
      .catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || `Upload error: ${response.status}`);
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

export async function deleteFolder(folderId: string): Promise<void> {
  await apiFetch(`/api/folders/${folderId}`, { method: "DELETE" });
}

export async function fetchBreadcrumbs(
  folderId: string
): Promise<Breadcrumb[]> {
  const res = await apiFetch(`/api/folders/${folderId}/breadcrumbs`);
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

export interface NotionSyncResult {
  fast: { processed: number; errors: number };
  full: { reachable: number; tombstoned: number };
  synced_at: string;
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
): Promise<NotionSyncResult> {
  const res = await apiFetch(`/api/notion/configs/${configId}/sync`, {
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
