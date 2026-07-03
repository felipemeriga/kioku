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
  const [configs, setConfigs] = useState<NotionConfig[]>([]);
  const [folders, setFolders] = useState<{ id: string; name: string }[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeJobsByConfig, setActiveJobsByConfig] = useState<Record<string, IngestionJob>>({});
  const pollTimers = useRef<Record<string, number>>({});

  const refresh = useCallback(async () => {
    try {
      const [cfgs, fs] = await Promise.all([fetchNotionConfigs(), fetchFolders(null)]);
      setConfigs(cfgs);
      setFolders(fs.map((f) => ({ id: f.id, name: f.name })));
    } catch (e) {
      setError(String(e));
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
        } catch (e) {
          stopPolling(configId);
          setError(String(e));
        }
      };
      void tick();
      pollTimers.current[configId] = window.setInterval(tick, 2000);
    },
    [refresh],
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
      } catch {
        // non-fatal
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
    } catch (e) {
      setError(String(e));
    }
  };

  const handleReconcile = async (id: string) => {
    try {
      const { job_id } = await reconcileNotionNow(id);
      startPolling(id, job_id);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDisconnect = async (id: string) => {
    const deleteDocs = window.confirm(
      "Delete all Notion-sourced documents from the mapped folder?\n\nOK = delete\nCancel = keep",
    );
    try {
      await disconnectNotion(id, deleteDocs);
      await refresh();
    } catch (e) {
      setError(String(e));
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
                <Stack direction="row" justifyContent="space-between" alignItems="center">
                  <Box>
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
                  <Stack direction="row" spacing={1}>
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
                      onClick={() => handleDisconnect(cfg.id)}
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

      <ConnectDialog
        open={dialogOpen}
        folders={folders}
        onClose={() => setDialogOpen(false)}
        onConnected={async () => {
          setDialogOpen(false);
          await refresh();
        }}
      />
    </Card>
  );
}

function ConnectDialog({
  open,
  folders,
  onClose,
  onConnected,
}: {
  open: boolean;
  folders: { id: string; name: string }[];
  onClose: () => void;
  onConnected: () => void;
}) {
  const [token, setToken] = useState("");
  const [rootFolderId, setRootFolderId] = useState("");
  const [pageOptions, setPageOptions] = useState<NotionPageOption[]>([]);
  const [selectedPage, setSelectedPage] = useState<NotionPageOption | null>(null);
  const [loadingPages, setLoadingPages] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPages = useCallback(async () => {
    if (!token) return;
    setLoadingPages(true);
    setError(null);
    try {
      const opts = await listNotionPages(token, "");
      setPageOptions(opts);
    } catch (e) {
      setError(`Could not load Notion pages: ${e}`);
    } finally {
      setLoadingPages(false);
    }
  }, [token]);

  const canSubmit = useMemo(
    () => !!token && !!rootFolderId && !!selectedPage,
    [token, rootFolderId, selectedPage],
  );

  const submit = async () => {
    if (!selectedPage) return;
    try {
      await connectNotion({
        root_folder_id: rootFolderId,
        notion_page_id: selectedPage.id,
        notion_page_title: selectedPage.title,
        integration_token: token,
      });
      onConnected();
    } catch (e) {
      setError(String(e));
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
          <FormControl fullWidth>
            <InputLabel>Rag root folder</InputLabel>
            <Select
              value={rootFolderId}
              label="Rag root folder"
              onChange={(e) => setRootFolderId(e.target.value)}
            >
              {folders.map((f) => (
                <MenuItem key={f.id} value={f.id}>
                  {f.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={submit} disabled={!canSubmit} variant="contained">
          Connect
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
