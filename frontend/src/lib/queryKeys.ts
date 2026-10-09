/**
 * Central query-key factory so every useQuery/invalidateQueries call site
 * agrees on the same keys. Keys are arrays; the first element names the entity
 * and the rest are the dependencies (folderId, conversationId, …).
 */
export const qk = {
  conversations: () => ["conversations"] as const,
  conversation: (id: string) => ["conversation", id] as const,

  documents: (folderId: string | null) =>
    ["documents", folderId ?? "root"] as const,
  folders: (parentId: string | null) =>
    ["folders", parentId ?? "root"] as const,
  breadcrumbs: (folderId: string) => ["breadcrumbs", folderId] as const,

  briefing: (folderId: string) => ["briefing", folderId] as const,
  documentation: (folderId: string) => ["documentation", folderId] as const,
  folderStatus: (folderId: string) => ["folder-status", folderId] as const,

  mem0Status: (rootFolderId: string) => ["mem0-status", rootFolderId] as const,
  folderMemories: (rootFolderId: string) =>
    ["folder-memories", rootFolderId] as const,

  apiKeys: () => ["api-keys"] as const,
  notionConfigs: () => ["notion-configs"] as const,
  notionPending: (configId: string) => ["notion-pending", configId] as const,

  documentFilters: () => ["document-filters"] as const,
  documentContent: (filename: string, folderId: string | null) =>
    ["document-content", filename, folderId ?? "root"] as const,

  ingestionStatus: () => ["ingestion-status"] as const,
  ingestionJob: (jobId: string) => ["ingestion-job", jobId] as const,
};
