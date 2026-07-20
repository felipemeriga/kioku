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
import { Alert, Box, LinearProgress, Stack, Typography } from "@mui/material";

import {
  fetchActiveIngestionJobs,
  fetchBreadcrumbs,
  fetchNotionConfigs,
  type IngestionJob,
  type NotionConfig,
} from "../lib/api";
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

export function NotionSyncBanner({ folderId }: { folderId: string }) {
  const [config, setConfig] = useState<NotionConfig | null>(null);
  const [job, setJob] = useState<IngestionJob | null>(null);
  const rootIdRef = useRef<string | null>(null);
  const hadJobRef = useRef(false);

  useEffect(() => {
    // Keyed by folderId at the call site, so this mounts fresh per folder —
    // no synchronous state reset needed here.
    let cancelled = false;
    let timer: number | null = null;

    const loadConfig = async (rootId: string) => {
      const cfgs = await fetchNotionConfigs();
      const cfg = cfgs.find((c) => c.root_folder_id === rootId) ?? null;
      if (!cancelled) setConfig(cfg);
      return cfg;
    };

    const tick = async () => {
      const rootId = rootIdRef.current;
      if (!rootId) return;
      try {
        const active = await fetchActiveIngestionJobs();
        if (cancelled) return;
        const running =
          active.find(
            (j) => j.kind === "notion_sync" && j.root_folder_id === rootId
          ) ?? null;
        setJob(running);
        // When a sync we were watching finishes, refresh the config so the
        // idle "last synced" line / error reflects the new state.
        if (hadJobRef.current && !running) await loadConfig(rootId);
        hadJobRef.current = !!running;
      } catch {
        // Best-effort: keep the last known state on a transient failure.
      }
    };

    (async () => {
      try {
        const crumbs = await fetchBreadcrumbs(folderId);
        const rootId = crumbs[0]?.id ?? folderId;
        rootIdRef.current = rootId;
        const cfg = await loadConfig(rootId);
        if (cancelled || !cfg) return; // not a Notion folder → no banner, no poll
        await tick();
        if (!cancelled) timer = window.setInterval(tick, POLL_MS);
      } catch {
        // No breadcrumbs / not authorized → render nothing.
      }
    })();

    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [folderId]);

  if (!config) return null;

  const wrapSx = {
    px: 3,
    py: 1.5,
    borderBottom: `1px solid ${brand.line}`,
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
      <Typography variant="caption" color="text.secondary">
        Notion · synced · last update {formatTs(lastSync)}
      </Typography>
    </Box>
  );
}

export default NotionSyncBanner;
