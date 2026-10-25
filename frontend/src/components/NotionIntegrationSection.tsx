import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  InputLabel,
  LinearProgress,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { messageFromError, useToast } from "./ToastProvider";
import { brand } from "../theme";
import { Link as RouterLink } from "react-router-dom";

import {
  connectNotion,
  disconnectNotion,
  fetchActiveIngestionJobs,
  fetchFolders,
  fetchIngestionJob,
  fetchNotionConfigs,
  fetchNotionPending,
  listNotionPages,
  reconcileNotionNow,
  syncNotionNow,
  type IngestionJob,
  type NotionConfig,
  type NotionPageOption,
  type NotionPendingResponse,
} from "../lib/api";
import { notionSyncProgress } from "../lib/notionProgress";

export function NotionIntegrationSection() {
  const toast = useToast();
  const [configs, setConfigs] = useState<NotionConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [folders, setFolders] = useState<{ id: string; name: string }[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disconnectTarget, setDisconnectTarget] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const [activeJobsByConfig, setActiveJobsByConfig] = useState<
    Record<string, IngestionJob>
  >({});
  const [pendingByConfig, setPendingByConfig] = useState<
    Record<string, NotionPendingResponse | "loading">
  >({});
  const pollTimers = useRef<Record<string, number>>({});

  const refresh = useCallback(async () => {
    try {
      const [cfgs, fs] = await Promise.all([
        fetchNotionConfigs(),
        fetchFolders(null),
      ]);
      setError(null);
      setConfigs(cfgs);
      setFolders(fs.map((f) => ({ id: f.id, name: f.name })));
    } catch (err) {
      setError(`Couldn't load Notion configs: ${messageFromError(err)}`);
    } finally {
      setLoading(false);
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
            "warning"
          );
        }
      };
      void tick();
      pollTimers.current[configId] = window.setInterval(tick, 2000);
    },
    [refresh, toast]
  );

  useEffect(() => {
    let cancelled = false;
    const timers = pollTimers.current;
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

        console.warn("[Notion] failed to resume active-job polling:", err);
      }
    })();
    return () => {
      cancelled = true;
      for (const configId of Object.keys(timers)) stopPolling(configId);
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
      // The pending list is about to change — clear the stale snapshot.
      setPendingByConfig((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      toast.showSuccess("Full reconciliation started.");
    } catch (err) {
      toast.showError(err, "Couldn't start reconciliation.");
    }
  };

  const handleCheckPending = async (id: string) => {
    setPendingByConfig((prev) => ({ ...prev, [id]: "loading" }));
    try {
      const result = await fetchNotionPending(id);
      setPendingByConfig((prev) => ({ ...prev, [id]: result }));
    } catch (err) {
      setPendingByConfig((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      toast.showError(err, "Couldn't check pending pages.");
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
          : "Disconnected. Docs kept in the folder."
      );
    } catch (err) {
      toast.showError(err, "Couldn't disconnect Notion.");
    }
  };

  return (
    <Box
      data-testid="notion-settings-section"
      sx={{
        display: "flex",
        flexDirection: "column",
        gap: "24px",
        width: "100%",
      }}
    >
      <Box
        data-testid="notion-settings-panel"
        sx={{
          border: `1px solid ${brand.line}`,
          borderRadius: "8px",
          bgcolor: brand.surface,
          overflow: "hidden",
        }}
      >
        <Box
          sx={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "16px",
            p: "20px 24px",
            borderBottom: `1px solid ${brand.line}`,
            "@media(max-width:780px)": { p: "18px", alignItems: "flex-start" },
          }}
        >
          <Box>
            <Typography
              component="h2"
              sx={{ fontSize: 21, fontWeight: 600, lineHeight: 1.3 }}
            >
              Notion syncs
            </Typography>
            <Typography
              sx={{
                fontSize: 13,
                lineHeight: 1.55,
                color: brand.muted,
                mt: "5px",
              }}
            >
              Bring a Notion page and its children into a Kioku folder.
            </Typography>
          </Box>
          <Button
            variant="contained"
            onClick={() => setDialogOpen(true)}
            sx={{ minHeight: 44, flexShrink: 0 }}
          >
            Connect folder
          </Button>
        </Box>
        <Box sx={{ p: "24px", "@media(max-width:780px)": { p: "20px" } }}>
          {error && (
            <Alert
              severity="error"
              sx={{ mb: 2 }}
              action={<Button onClick={() => void refresh()}>Retry</Button>}
            >
              {error}
            </Alert>
          )}
          {loading && (
            <Typography role="status" sx={{ color: brand.muted, fontSize: 14 }}>
              Loading Notion syncs…
            </Typography>
          )}
          {!loading && !error && configs.length === 0 && (
            <Typography sx={{ color: brand.muted, fontSize: 14, py: 2 }}>
              No folders synced with Notion yet. Connect a folder to bring its
              Notion pages into Kioku.
            </Typography>
          )}
          {configs.map((cfg, index) => {
            const activeJob = activeJobsByConfig[cfg.id];
            const syncing = !!activeJob;
            const pending = pendingByConfig[cfg.id];
            const mappedFolder = folders.find(
              (folder) => folder.id === cfg.root_folder_id
            );
            const progress = activeJob ? notionSyncProgress(activeJob) : null;
            return (
              <Box
                key={cfg.id}
                sx={{
                  pt: index ? "24px" : "18px",
                  pb: index < configs.length - 1 ? "24px" : 0,
                  borderBottom:
                    index < configs.length - 1
                      ? `1px solid ${brand.line}`
                      : undefined,
                }}
              >
                <Box
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 2,
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography
                      component="h3"
                      sx={{
                        fontSize: 17,
                        fontWeight: 600,
                        overflowWrap: "anywhere",
                      }}
                    >
                      {cfg.notion_page_title ??
                        mappedFolder?.name ??
                        "Notion connection"}
                    </Typography>
                    <Typography
                      sx={{
                        fontSize: 13,
                        lineHeight: 1.55,
                        color: brand.muted,
                        mt: "5px",
                      }}
                    >
                      Kioku folder:{" "}
                      <Box
                        component={RouterLink}
                        to={`/documents?folder=${cfg.root_folder_id}`}
                        sx={{ color: brand.muted, textUnderlineOffset: "3px" }}
                      >
                        {mappedFolder?.name ?? "Open mapped folder"}
                      </Box>
                    </Typography>
                    <Typography
                      sx={{
                        fontSize: 13,
                        color: brand.muted,
                        mt: "5px",
                        overflowWrap: "anywhere",
                      }}
                    >
                      Root page: {cfg.notion_page_title ?? cfg.notion_page_id}
                    </Typography>
                  </Box>
                  <Typography
                    sx={{
                      color: cfg.last_error ? brand.amber : brand.green,
                      fontSize: 12,
                      whiteSpace: "nowrap",
                    }}
                  >
                    ●{" "}
                    {syncing
                      ? "Syncing"
                      : cfg.last_error
                      ? "Needs attention"
                      : "Connected"}
                  </Typography>
                </Box>
                <Box
                  component="dl"
                  sx={{
                    m: "20px 0 22px",
                    pt: "8px",
                    borderTop: `1px solid ${brand.line}`,
                    "& > div": {
                      display: "flex",
                      justifyContent: "space-between",
                      gap: "16px",
                      py: "6px",
                      fontSize: 13,
                    },
                    "& dt": { color: brand.muted },
                    "& dd": { m: 0, textAlign: "right" },
                  }}
                >
                  <Box>
                    <dt>Last sync</dt>
                    <dd>{formatTs(cfg.last_fast_sync_at)}</dd>
                  </Box>
                  <Box>
                    <dt>Latest reconciliation</dt>
                    <dd>{formatTs(cfg.last_full_sync_at)}</dd>
                  </Box>
                  <Box>
                    <dt>Checks for changes</dt>
                    <dd>Every {cfg.fast_poll_interval_min} minutes</dd>
                  </Box>
                </Box>
                {cfg.last_error && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    {cfg.last_error}
                  </Alert>
                )}
                {progress && (
                  <Box role="status" sx={{ mb: "18px" }}>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      sx={{ mb: 1 }}
                    >
                      <Typography sx={{ fontSize: 13, color: brand.muted }}>
                        {progress.label}
                      </Typography>
                      {progress.pct !== null && (
                        <Typography sx={{ fontSize: 13, color: brand.muted }}>
                          {progress.pct}%
                        </Typography>
                      )}
                    </Stack>
                    <LinearProgress
                      variant={
                        progress.pct === null ? "indeterminate" : "determinate"
                      }
                      value={progress.pct ?? undefined}
                      sx={{ height: 5, borderRadius: "2px" }}
                    />
                  </Box>
                )}
                <Box
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "14px",
                    p: "13px 16px",
                    border: `1px solid ${brand.cyan}44`,
                    bgcolor: `${brand.cyan}08`,
                    borderRadius: "5px",
                    color: brand.muted,
                    fontSize: 14,
                  }}
                >
                  <Typography sx={{ fontSize: 14 }}>
                    {pending === "loading"
                      ? "Checking for changed pages…"
                      : pending
                      ? pending.pending.length === 0
                        ? `All ${pending.total_in_notion} Notion pages are synced.`
                        : `${pending.pending.length} of ${pending.total_in_notion} pages need to sync.`
                      : "Check for Notion pages that are new or updated."}
                  </Typography>
                  <Button
                    onClick={() => void handleCheckPending(cfg.id)}
                    disabled={pending === "loading"}
                    sx={{
                      color: brand.cyan,
                      fontSize: 13,
                      minHeight: 32,
                      p: 0,
                      lineHeight: 1.55,
                      whiteSpace: "nowrap",
                      minWidth: 0,
                      flexShrink: 0,
                    }}
                  >
                    {pending === "loading" ? "Checking…" : "Check for changes"}
                  </Button>
                </Box>
                {pending &&
                  pending !== "loading" &&
                  pending.pending.length > 0 && (
                    <Box
                      component="ul"
                      sx={{
                        my: "16px",
                        pl: "22px",
                        color: brand.muted,
                        fontSize: 14,
                      }}
                    >
                      {pending.pending.map((page) => (
                        <Box
                          component="li"
                          key={page.page_id}
                          sx={{ py: "3px" }}
                        >
                          {page.title || page.page_id} ·{" "}
                          {page.reason === "missing"
                            ? "Not in Kioku"
                            : "Edited since last ingest"}
                        </Box>
                      ))}
                    </Box>
                  )}
                <Box
                  sx={{
                    display: "flex",
                    gap: "10px",
                    flexWrap: "wrap",
                    mt: "22px",
                  }}
                >
                  <Button
                    variant="contained"
                    onClick={() => void handleSync(cfg.id)}
                    disabled={syncing}
                    sx={{ minHeight: 44 }}
                  >
                    {syncing ? "Syncing…" : "Sync now"}
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() => void handleReconcile(cfg.id)}
                    disabled={syncing}
                    title="Detect removed pages and re-ingest changed content"
                    sx={{ minHeight: 44 }}
                  >
                    Reconcile
                  </Button>
                  <Button
                    variant="outlined"
                    color="error"
                    onClick={() =>
                      requestDisconnect(
                        cfg.id,
                        cfg.notion_page_title ?? cfg.notion_page_id
                      )
                    }
                    sx={{ minHeight: 44 }}
                  >
                    Disconnect
                  </Button>
                </Box>
                <Typography
                  sx={{
                    fontSize: 13,
                    color: brand.muted,
                    mt: "16px",
                    lineHeight: 1.7,
                  }}
                >
                  Reconciliation detects updated and removed pages.
                  Disconnecting can keep the imported documents.
                </Typography>
              </Box>
            );
          })}
        </Box>
      </Box>
      <Box
        sx={{
          p: "24px",
          border: `1px solid ${brand.line}`,
          borderRadius: "8px",
          bgcolor: brand.surface,
          "@media(max-width:780px)": { p: "20px" },
        }}
      >
        <Typography
          component="h3"
          sx={{ fontSize: 17, fontWeight: 600, mb: "12px" }}
        >
          Folder integrations
        </Typography>
        <Typography
          sx={{ fontSize: 14, color: brand.muted, mb: "16px", lineHeight: 1.7 }}
        >
          You can also manage integrations directly from a folder in Documents.
        </Typography>
        <Button
          component={RouterLink}
          to="/documents"
          variant="outlined"
          sx={{ minHeight: 44 }}
        >
          Open folder integrations
        </Button>
      </Box>
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
    </Box>
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
   *  GitHubConnectDialog signature so the per-folder
   *  FolderIntegrationsDialog can reuse the same dialog. */
  fixedFolderId?: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [token, setToken] = useState("");
  const [rootFolderId, setRootFolderId] = useState(fixedFolderId ?? "");
  const [pageOptions, setPageOptions] = useState<NotionPageOption[]>([]);
  const [selectedPage, setSelectedPage] = useState<NotionPageOption | null>(
    null
  );
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
    [token, rootFolderId, selectedPage, busy]
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
            1. Create an integration at notion.so/my-integrations. 2. Share your
            root page with it. 3. Paste the integration token below.
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
            renderInput={(params) => (
              <TextField {...params} label="Notion root page" />
            )}
            disabled={pageOptions.length === 0}
          />
          {!fixedFolderId && (
            <FormControl fullWidth>
              <InputLabel>Kioku folder</InputLabel>
              <Select
                value={rootFolderId}
                label="Kioku folder"
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
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={!canSubmit} variant="contained">
          {busy ? "Connecting…" : "Connect"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function formatTs(iso: string | null): string {
  if (!iso) return "Never";
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return iso;
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const time = value.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (value.toDateString() === today.toDateString()) return `Today, ${time}`;
  if (value.toDateString() === yesterday.toDateString())
    return `Yesterday, ${time}`;
  return `${value.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(value.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}),
  })}, ${time}`;
}
