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
import RefreshIcon from "@mui/icons-material/Refresh";
import DeleteIcon from "@mui/icons-material/Delete";
import { messageFromError, useToast } from "./ToastProvider";
import CornerCard from "./neo/CornerCard";
import { brand, fonts } from "../theme";

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
      for (const configId of Object.keys(pollTimers.current))
        stopPolling(configId);
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
    <CornerCard
      color={brand.cyan}
      sx={{
        p: "22px 24px",
        display: "flex",
        flexDirection: "column",
        gap: "14px",
      }}
    >
      {/* Section heading row */}
      <Box sx={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <Typography
          sx={{ fontFamily: fonts.mono, fontSize: 12, color: brand.cyan }}
        >
          02
        </Typography>
        <Typography sx={{ fontSize: 19, fontWeight: 600, m: 0 }}>
          Notion Integration
        </Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Button
          onClick={() => setDialogOpen(true)}
          sx={{
            height: 36,
            px: "14px",
            border: 0,
            borderRadius: "4px",
            backgroundImage: `linear-gradient(90deg, ${brand.magentaDeep} 0%, ${brand.purple} 100%)`,
            color: "#ffffff",
            fontWeight: 600,
            fontSize: 13,
            textTransform: "none",
            "&:hover": {
              backgroundImage: `linear-gradient(90deg, ${brand.magenta} 0%, ${brand.purple} 100%)`,
            },
          }}
        >
          Connect Notion
        </Button>
      </Box>

      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {configs.length === 0 && (
        <Typography sx={{ fontSize: 14, color: brand.muted }}>
          No Notion pages connected. Connect a Notion root page to sync its
          content into a rag root folder.
        </Typography>
      )}

      {configs.map((cfg) => {
        const activeJob = activeJobsByConfig[cfg.id];
        const syncing = !!activeJob;
        return (
          <Box
            key={cfg.id}
            sx={{
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              p: "14px 16px",
              borderRadius: "4px",
              border: `1px solid ${brand.cyan}44`,
              bgcolor: `${brand.cyan}08`,
            }}
          >
            {/* Config title */}
            <Typography sx={{ fontSize: 16, fontWeight: 600 }}>
              {cfg.notion_page_title ?? cfg.notion_page_id}
            </Typography>

            {/* Sync detail grid */}
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                gap: "6px 16px",
                fontFamily: fonts.mono,
                fontSize: 12,
                color: brand.text,
              }}
            >
              <span>
                <Box component="span" sx={{ color: brand.muted }}>
                  ROOT FOLDER{" "}
                </Box>
                {folderName(folders, cfg.root_folder_id)}
              </span>
              <span>
                <Box component="span" sx={{ color: brand.muted }}>
                  POLL{" "}
                </Box>
                every {cfg.fast_poll_interval_min} min
              </span>
              <span>
                <Box component="span" sx={{ color: brand.muted }}>
                  LAST FAST{" "}
                </Box>
                {formatTs(cfg.last_fast_sync_at)}
              </span>
              <span>
                <Box component="span" sx={{ color: brand.muted }}>
                  LAST FULL{" "}
                </Box>
                {formatTs(cfg.last_full_sync_at)}
              </span>
            </Box>

            {cfg.last_error && (
              <Alert severity="warning" sx={{ mt: 0 }}>
                {cfg.last_error}
              </Alert>
            )}

            {/* Action buttons */}
            <Box
              sx={{
                display: "flex",
                gap: "8px",
                flexWrap: "wrap",
                alignItems: "center",
              }}
            >
              <Button
                onClick={() => handleCheckPending(cfg.id)}
                disabled={pendingByConfig[cfg.id] === "loading"}
                title="List pages in Notion that are missing from kioku or edited since their last ingest — exactly what Reconcile would sync"
                sx={{
                  height: 34,
                  px: "12px",
                  borderRadius: "4px",
                  border: `1px solid ${brand.lineGlow}`,
                  bgcolor: "transparent",
                  color: brand.text,
                  fontSize: 13,
                  fontWeight: 600,
                  textTransform: "none",
                  "&:hover": { bgcolor: `${brand.cyan}10` },
                  "&.Mui-disabled": { opacity: 0.5 },
                }}
              >
                {pendingByConfig[cfg.id] === "loading"
                  ? "Checking…"
                  : "Check pending"}
              </Button>
              <Button
                startIcon={<RefreshIcon />}
                onClick={() => handleSync(cfg.id)}
                disabled={syncing}
                sx={{
                  height: 34,
                  px: "12px",
                  borderRadius: "4px",
                  border: `1px solid ${brand.cyan}`,
                  bgcolor: `${brand.cyan}10`,
                  color: brand.cyan,
                  fontSize: 13,
                  fontWeight: 600,
                  textTransform: "none",
                  "&:hover": { bgcolor: `${brand.cyan}20` },
                  "&.Mui-disabled": { opacity: 0.5 },
                }}
              >
                {syncing ? "Syncing…" : "Sync now"}
              </Button>
              <Button
                onClick={() => handleReconcile(cfg.id)}
                disabled={syncing}
                title="Full walk: detects deletions and re-ingests any drift"
                sx={{
                  height: 34,
                  px: "12px",
                  borderRadius: "4px",
                  border: `1px solid ${brand.lineGlow}`,
                  bgcolor: "transparent",
                  color: brand.text,
                  fontSize: 13,
                  fontWeight: 600,
                  textTransform: "none",
                  "&:hover": { bgcolor: `${brand.cyan}10` },
                  "&.Mui-disabled": { opacity: 0.5 },
                }}
              >
                Reconcile
              </Button>
              <Box sx={{ flexGrow: 1 }} />
              <Button
                startIcon={<DeleteIcon />}
                onClick={() =>
                  requestDisconnect(
                    cfg.id,
                    cfg.notion_page_title ?? cfg.notion_page_id
                  )
                }
                sx={{
                  height: 34,
                  px: "12px",
                  borderRadius: "4px",
                  border: `1px solid ${brand.red}66`,
                  bgcolor: "transparent",
                  color: brand.red,
                  fontSize: 13,
                  fontWeight: 600,
                  textTransform: "none",
                  "&:hover": { bgcolor: `${brand.red}14` },
                }}
              >
                Disconnect
              </Button>
            </Box>

            {/* Progress bar for active job */}
            {activeJob &&
              (() => {
                const { pct, label } = notionSyncProgress(activeJob);
                return (
                  <Box sx={{ mt: 0.5 }}>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="baseline"
                      sx={{ mb: 0.5 }}
                    >
                      <Typography variant="caption" color="text.secondary">
                        {label}
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
              })()}

            {/* Pending list */}
            {(() => {
              const pending = pendingByConfig[cfg.id];
              if (!pending || pending === "loading") return null;
              return (
                <Box sx={{ mt: 0.5 }}>
                  {pending.pending.length === 0 ? (
                    <Alert severity="success" sx={{ py: 0 }}>
                      All {pending.total_in_notion} Notion pages are synced.
                    </Alert>
                  ) : (
                    <Alert severity="info" sx={{ py: 0.5 }}>
                      <Typography variant="body2" sx={{ mb: 0.5 }}>
                        {pending.pending.length} of {pending.total_in_notion}{" "}
                        pages left to sync — run Reconcile to ingest them:
                      </Typography>
                      <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                        {pending.pending.map((p) => (
                          <Typography
                            key={p.page_id}
                            component="li"
                            variant="body2"
                          >
                            {p.title || p.page_id}{" "}
                            <Typography
                              component="span"
                              variant="caption"
                              color="text.secondary"
                            >
                              (
                              {p.reason === "missing"
                                ? "not in kioku"
                                : "edited since last ingest"}
                              )
                            </Typography>
                          </Typography>
                        ))}
                      </Box>
                    </Alert>
                  )}
                </Box>
              );
            })()}
          </Box>
        );
      })}

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
    </CornerCard>
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

function folderName(
  folders: { id: string; name: string }[],
  id: string
): string {
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
