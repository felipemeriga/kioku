import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import DeleteIcon from "@mui/icons-material/Delete";
import { messageFromError, useToast } from "./ToastProvider";

import {
  connectNotion,
  disconnectNotion,
  fetchActiveIngestionJobs,
  fetchFolders,
  fetchIngestionJob,
  fetchNotionConfigs,
  listNotionPages,
  reconcileNotionNow,
  syncNotionNow,
  type IngestionJob,
  type NotionConfig,
  type NotionPageOption,
} from "../lib/api";

export function NotionIntegrationSection() {
  const toast = useToast();
  const [configs, setConfigs] = useState<NotionConfig[]>([]);
  const [folders, setFolders] = useState<{ id: string; name: string }[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const [activeJobsByConfig, setActiveJobsByConfig] = useState<Record<string, IngestionJob>>({});
  const pollTimers = useRef<Record<string, number>>({});

  const refresh = useCallback(async () => {
    try {
      const [cfgs, fs] = await Promise.all([fetchNotionConfigs(), fetchFolders(null)]);
      setConfigs(cfgs);
      setFolders(fs.map((f) => ({ id: f.id, name: f.name })));
    } catch (err) {
      setError(`Couldn't load Notion configs: ${messageFromError(err)}`);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const stopPolling = (configId: string) => {
    const t = pollTimers.current[configId];
    if (t) {
      window.clearInterval(t);
      delete pollTimers.current[configId];
    }
  };

  const startPolling = useCallback(
    (configId: string, jobId: string) => {
      stopPolling(configId);
      const tick = async () => {
        try {
          const job = await fetchIngestionJob(jobId);
          setActiveJobsByConfig((prev) => ({ ...prev, [configId]: job }));
          if (job.status === "completed" || job.status === "failed") {
            stopPolling(configId);
            setActiveJobsByConfig((prev) => {
              const next = { ...prev };
              delete next[configId];
              return next;
            });
            await refresh();
          }
        } catch (err) {
          stopPolling(configId);
          toast.show(
            `Lost track of the Notion sync job: ${messageFromError(err)}`,
            "warning",
          );
        }
      };
      void tick();
      pollTimers.current[configId] = window.setInterval(tick, 2000);
    },
    [refresh, toast],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const active = await fetchActiveIngestionJobs();
        if (cancelled) return;
        const notionSyncJobs = active.filter((j) => j.kind === "notion_sync");
        for (const job of notionSyncJobs) {
          startPolling(job.source_ref, job.id);
        }
      } catch (err) {
        // Non-fatal: user just won't see the resumed progress bar for in-flight
        // syncs that started before the page loaded.
        // eslint-disable-next-line no-console
        console.warn("[Notion] failed to resume active-job polling:", err);
      }
    })();
    return () => {
      cancelled = true;
      for (const configId of Object.keys(pollTimers.current)) stopPolling(configId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSync = async (id: string) => {
    try {
      const { job_id } = await syncNotionNow(id);
      startPolling(id, job_id);
      toast.showSuccess("Sync started.");
    } catch (err) {
      toast.showError(err, "Couldn't start the sync.");
    }
  };

  const handleReconcile = async (id: string) => {
    try {
      const { job_id } = await reconcileNotionNow(id);
      startPolling(id, job_id);
      toast.showSuccess("Full reconciliation started.");
    } catch (err) {
      toast.showError(err, "Couldn't start reconciliation.");
    }
  };

  // Two-step disconnect: open confirm dialog, then execute on the second click.
  // Replaces the previous window.confirm() which was blocking and un-styled.
  const requestDisconnect = (id: string, title: string) =>
    setDisconnectTarget({ id, title });

  const handleConfirmDisconnect = async (deleteDocs: boolean) => {
    if (!disconnectTarget) return;
    const { id } = disconnectTarget;
    setDisconnectTarget(null);
    try {
      await disconnectNotion(id, deleteDocs);
      await refresh();
      toast.showSuccess(
        deleteDocs
          ? "Disconnected. Notion-sourced docs removed."
          : "Disconnected. Docs kept in the folder.",
      );
    } catch (err) {
      toast.showError(err, "Couldn't disconnect Notion.");
    }
  };

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" justifyContent="space-between" mb={2}>
          <Typography variant="h6">Notion Integration</Typography>
          <Button variant="contained" onClick={() => setDialogOpen(true)}>
            Connect Notion
          </Button>
        </Stack>

        {error && (
          <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {configs.length === 0 && (
          <Typography color="text.secondary">
            No Notion pages connected. Connect a Notion root page to sync its content into a rag root folder.
          </Typography>
        )}

        <Stack divider={<Divider flexItem />} spacing={2}>
          {configs.map((cfg) => {
            const activeJob = activeJobsByConfig[cfg.id];
            const syncing = !!activeJob;
            return (
              <Box key={cfg.id}>
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  spacing={2}
                >
                  <Box sx={{ minWidth: 0, flex: 1 }}>
                    <Typography fontWeight="bold">
                      {cfg.notion_page_title ?? cfg.notion_page_id}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Root folder: {folderName(folders, cfg.root_folder_id)} · Poll every{" "}
                      {cfg.fast_poll_interval_min} min
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      Last fast: {formatTs(cfg.last_fast_sync_at)} · Last full:{" "}
                      {formatTs(cfg.last_full_sync_at)}
                    </Typography>
                    {cfg.last_error && (
                      <Alert severity="warning" sx={{ mt: 1 }}>
                        {cfg.last_error}
                      </Alert>
                    )}
                  </Box>
                  <Stack
                    direction="row"
                    spacing={1}
                    sx={{ flexShrink: 0, "& .MuiButton-root": { whiteSpace: "nowrap" } }}
                  >
                    <Button
                      startIcon={<RefreshIcon />}
                      onClick={() => handleSync(cfg.id)}
                      disabled={syncing}
                    >
                      {syncing ? "Syncing…" : "Sync now"}
                    </Button>
                    <Button
                      onClick={() => handleReconcile(cfg.id)}
                      disabled={syncing}
                      title="Full walk: detects deletions and re-ingests any drift"
                    >
                      Reconcile
                    </Button>
                    <Button
                      color="error"
                      startIcon={<DeleteIcon />}
                      onClick={() =>
                        requestDisconnect(
                          cfg.id,
                          cfg.notion_page_title ?? cfg.notion_page_id,
                        )
                      }
                    >
                      Disconnect
                    </Button>
                  </Stack>
                </Stack>
                {activeJob && (
                  <Alert severity="info" sx={{ mt: 1 }}>
                    Syncing {activeJob.processed_pages ?? 0}/{activeJob.total_pages ?? "?"} pages —
                    batches {activeJob.processed_batches}/{activeJob.total_batches}
                  </Alert>
                )}
              </Box>
            );
          })}
        </Stack>
      </CardContent>

      <NotionConnectDialog
        open={dialogOpen}
        rootFolders={folders}
        onClose={() => setDialogOpen(false)}
        onConnected={async () => {
          setDialogOpen(false);
          await refresh();
        }}
      />

      <Dialog
        open={!!disconnectTarget}
        onClose={() => setDisconnectTarget(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Disconnect Notion?</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 1 }}>
            Disconnecting <strong>{disconnectTarget?.title}</strong> stops
            future syncs. Choose whether to keep the documents already ingested
            from this Notion source, or remove them from the mapped folder.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ pb: 2, pr: 3 }}>
          <Button onClick={() => setDisconnectTarget(null)}>Cancel</Button>
          <Button onClick={() => handleConfirmDisconnect(false)}>
            Keep documents
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => handleConfirmDisconnect(true)}
          >
            Delete documents
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

export function NotionConnectDialog({
  open,
  rootFolders,
  fixedFolderId,
  onClose,
  onConnected,
}: {
  open: boolean;
  rootFolders: { id: string; name: string }[];
  /** If set, the folder picker is hidden and this folder is used. Matches the
   *  Mem0ConnectDialog / GitHubConnectDialog signature so the per-folder
   *  FolderIntegrationsDialog can reuse the same dialog. */
  fixedFolderId?: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [token, setToken] = useState("");
  const [rootFolderId, setRootFolderId] = useState(fixedFolderId ?? "");
  const [pageOptions, setPageOptions] = useState<NotionPageOption[]>([]);
  const [selectedPage, setSelectedPage] = useState<NotionPageOption | null>(null);
  const [loadingPages, setLoadingPages] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Keep the internal folder id in sync when the caller changes fixedFolderId
  // (dialog reused for a different folder without unmounting).
  useEffect(() => {
    if (fixedFolderId) setRootFolderId(fixedFolderId);
  }, [fixedFolderId]);

  const loadPages = useCallback(async () => {
    if (!token) return;
    setLoadingPages(true);
    setError(null);
    try {
      const opts = await listNotionPages(token, "");
      setPageOptions(opts);
    } catch (err) {
      setError(`Could not load Notion pages: ${messageFromError(err)}`);
    } finally {
      setLoadingPages(false);
    }
  }, [token]);

  const canSubmit = useMemo(
    () => !!token && !!rootFolderId && !!selectedPage && !busy,
    [token, rootFolderId, selectedPage, busy],
  );

  const submit = async () => {
    if (!selectedPage) return;
    setError(null);
    setBusy(true);
    try {
      await connectNotion({
        root_folder_id: rootFolderId,
        notion_page_id: selectedPage.id,
        notion_page_title: selectedPage.title,
        integration_token: token,
      });
      // Reset on success so a reopen starts clean (but keep folder for the
      // fixed variant since the caller is scoping to one folder anyway).
      setToken("");
      setPageOptions([]);
      setSelectedPage(null);
      if (!fixedFolderId) setRootFolderId("");
      onConnected();
    } catch (err) {
      setError(`Couldn't connect: ${messageFromError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Connect Notion</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            1. Create an integration at notion.so/my-integrations. 2. Share your root page with it.
            3. Paste the integration token below.
          </Typography>
          <TextField
            label="Notion integration token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            type="password"
            fullWidth
          />
          <Button onClick={loadPages} disabled={!token || loadingPages}>
            {loadingPages ? "Loading pages…" : "Load pages"}
          </Button>
          <Autocomplete<NotionPageOption>
            options={pageOptions}
            getOptionLabel={(o) => o.title}
            value={selectedPage}
            onChange={(_, v) => setSelectedPage(v)}
            renderInput={(params) => <TextField {...params} label="Notion root page" />}
            disabled={pageOptions.length === 0}
          />
          {!fixedFolderId && (
            <FormControl fullWidth>
              <InputLabel>Rag root folder</InputLabel>
              <Select
                value={rootFolderId}
                label="Rag root folder"
                onChange={(e) => setRootFolderId(e.target.value)}
              >
                {rootFolders.map((f) => (
                  <MenuItem key={f.id} value={f.id}>
                    {f.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        <Button onClick={submit} disabled={!canSubmit} variant="contained">
          {busy ? "Connecting…" : "Connect"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function folderName(folders: { id: string; name: string }[], id: string): string {
  return folders.find((f) => f.id === id)?.name ?? id;
}

function formatTs(iso: string | null): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
