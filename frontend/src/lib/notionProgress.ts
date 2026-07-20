import type { IngestionJob } from "./api";

export interface NotionSyncProgress {
  /** null → render an indeterminate bar (total not known yet). */
  pct: number | null;
  label: string;
}

/** Two-phase progress for a notion_sync job: pages first (ingest), then
 *  embedding batches. Indeterminate while still enumerating and neither
 *  total is known. Shared by the Settings panel and the folder banner so
 *  the two never diverge. */
export function notionSyncProgress(job: IngestionJob): NotionSyncProgress {
  const done = job.processed_pages ?? 0;
  const pages = job.total_pages ?? 0;
  const batches = job.total_batches ?? 0;

  if (pages > 0) {
    return {
      pct: Math.min(100, Math.round((done / pages) * 100)),
      label: `Syncing ${done}/${pages} pages`,
    };
  }
  if (batches > 0) {
    return {
      pct: Math.min(100, Math.round((job.processed_batches / batches) * 100)),
      label: `Embedding ${job.processed_batches}/${batches} batches`,
    };
  }
  if (done > 0) {
    // Total not known yet (still enumerating) but pages are landing.
    return {
      pct: null,
      label: `Syncing… ${done} page${done === 1 ? "" : "s"} done`,
    };
  }
  return { pct: null, label: "Syncing…" };
}
