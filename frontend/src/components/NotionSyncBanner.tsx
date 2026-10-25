/**
 * NotionSyncBanner — surfaces Notion sync state on a folder page.
 *
 * When a notion_sync job is running for this folder's root, shows a live
 * two-phase progress bar (pages → embedding batches), polling every few
 * seconds. When idle, shows a compact "last synced" line (or the last error).
 * Renders nothing for folders whose root has no Notion config, so it's safe
 * to drop onto every folder.
 */
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  LinearProgress,
  Stack,
  Typography,
} from "@mui/material";

import {
  fetchActiveIngestionJobs,
  fetchNotionConfigs,
  type IngestionJob,
} from "../lib/api";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { breadcrumbOptions, FOLDER_STALE_TIME } from "../lib/folderQueries";
import { qk } from "../lib/queryKeys";
import { notionSyncProgress } from "../lib/notionProgress";
import { brand } from "../theme";

const POLL_MS = 3000;

function formatTs(iso: string | null): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function NotionSyncBanner({
  folderId,
  onPagesSynced,
}: {
  folderId: string;
  /** Fired when a new page finishes syncing (processed_pages increases) and
   *  once more when the sync completes — so the caller can refresh its file
   *  list to show newly-ingested documents without a manual reload. */
  onPagesSynced?: () => void;
}) {
  const client = useQueryClient();
  const { data: crumbs } = useQuery(breadcrumbOptions(folderId));
  const { data: configs } = useQuery({
    queryKey: qk.notionConfigs(),
    queryFn: fetchNotionConfigs,
    staleTime: FOLDER_STALE_TIME,
  });
  const chainIds = new Set([folderId, ...(crumbs ?? []).map((c) => c.id)]);
  const config = configs?.find((c) => chainIds.has(c.root_folder_id)) ?? null;
  const rootId = config?.root_folder_id;

  const [job, setJob] = useState<IngestionJob | null>(null);
  const hadJobRef = useRef(false);
  // Latest processed_pages we've seen; -1 until the first observation so
  // opening a folder mid-sync doesn't fire a spurious refresh.
  const lastPagesRef = useRef(-1);
  // Keep the callback fresh without re-running the polling effect.
  const onPagesSyncedRef = useRef(onPagesSynced);
  useEffect(() => {
    onPagesSyncedRef.current = onPagesSynced;
  }, [onPagesSynced]);

  useEffect(() => {
    // Keyed by folderId at the call site, so this mounts fresh per folder —
    // no synchronous state reset needed here.
    let cancelled = false;
    let timer: number | null = null;

    const tick = async () => {
      if (!rootId) return;
      try {
        const active = await fetchActiveIngestionJobs();
        if (cancelled) return;
        const running =
          active.find(
            (j) => j.kind === "notion_sync" && j.root_folder_id === rootId
          ) ?? null;
        setJob(running);

        // A page landed since we last looked → tell the caller to refresh
        // its file list. Skip the very first observation (lastPagesRef < 0).
        const pages = running?.processed_pages ?? 0;
        if (running && pages !== lastPagesRef.current) {
          if (lastPagesRef.current >= 0 && pages > lastPagesRef.current) {
            onPagesSyncedRef.current?.();
          }
          lastPagesRef.current = pages;
        }

        // When a sync we were watching finishes, refresh the config so the
        // idle "last synced" line / error reflects the new state, and do a
        // final file-list refresh to catch the last page + any new folders.
        if (hadJobRef.current && !running) {
          await client.invalidateQueries({ queryKey: qk.notionConfigs() });
          onPagesSyncedRef.current?.();
          lastPagesRef.current = -1;
        }
        hadJobRef.current = !!running;
      } catch {
        // Best-effort: keep the last known state on a transient failure.
      }
    };

    if (rootId) {
      void tick();
      timer = window.setInterval(tick, POLL_MS);
    }

    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [rootId, client]);

  if (!config) return null;

  const wrapSx = {
    px: 2.5,
    py: 2,
    mb: 3,
    border: `1px solid ${brand.cyan}66`,
    borderRadius: 1.5,
    backgroundColor: `${brand.cyan}08`,
  } as const;

  if (job && (job.status === "queued" || job.status === "running")) {
    const { pct, label } = notionSyncProgress(job);
    return (
      <Box sx={wrapSx}>
        <Stack
          direction="row"
          justifyContent="space-between"
          alignItems="baseline"
          sx={{ mb: 0.5 }}
        >
          <Typography variant="caption" color="text.secondary">
            Notion · {label}
          </Typography>
          {pct !== null && (
            <Typography variant="caption" color="text.secondary">
              {pct}%
            </Typography>
          )}
        </Stack>
        <LinearProgress
          variant={pct === null ? "indeterminate" : "determinate"}
          value={pct ?? undefined}
          sx={{ height: 6, borderRadius: 3 }}
        />
      </Box>
    );
  }

  if (config.last_error) {
    return (
      <Box sx={wrapSx}>
        <Alert severity="warning" sx={{ py: 0 }}>
          Last Notion sync failed: {config.last_error}
        </Alert>
      </Box>
    );
  }

  const lastSync = config.last_full_sync_at ?? config.last_fast_sync_at;
  return (
    <Box sx={wrapSx}>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        gap={2}
      >
        <Typography sx={{ fontSize: 14, color: brand.muted }}>
          <Box component="strong" sx={{ color: brand.text, fontWeight: 500 }}>
            Notion connected
          </Box>{" "}
          · Last synced {formatTs(lastSync)}
        </Typography>
        <Button
          component={Link}
          to="/settings?tab=integrations"
          size="small"
          color="secondary"
        >
          Manage
        </Button>
      </Stack>
    </Box>
  );
}

export default NotionSyncBanner;
