import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import RefreshIcon from "@mui/icons-material/Refresh";
import GitHubIcon from "@mui/icons-material/GitHub";
import {
  connectGitHub,
  disconnectGitHub,
  fetchFolders,
  fetchGitHubConfigs,
  listGitHubRepos,
  syncGitHubNow,
} from "../lib/api";
import type { Folder, GitHubConfig, GitHubRepoOption } from "../lib/api";
import { messageFromError, useToast } from "./ToastProvider";

export function GitHubIntegrationSection() {
  const toast = useToast();
  const [configs, setConfigs] = useState<GitHubConfig[]>([]);
  const [rootFolders, setRootFolders] = useState<Folder[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<GitHubConfig | null>(
    null
  );
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [cfgs, fs] = await Promise.all([
        fetchGitHubConfigs(),
        fetchFolders(null),
      ]);
      setConfigs(cfgs);
      setRootFolders(fs);
    } catch (err) {
      toast.showError(err, "Couldn't load GitHub configs.");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSync = async (id: string) => {
    setBusyId(id);
    try {
      await syncGitHubNow(id);
      toast.showSuccess("GitHub sync queued.");
    } catch (err) {
      toast.showError(err, "Couldn't queue the GitHub sync.");
    } finally {
      setBusyId(null);
    }
  };

  const handleDisconnect = async (deleteDocs: boolean) => {
    if (!disconnectTarget) return;
    const { id } = disconnectTarget;
    setDisconnectTarget(null);
    try {
      await disconnectGitHub(id, deleteDocs);
      await refresh();
      toast.showSuccess(
        deleteDocs
          ? "Disconnected. GitHub-sourced docs removed."
          : "Disconnected. Docs kept in the folder.",
      );
    } catch (err) {
      toast.showError(err, "Couldn't disconnect GitHub.");
    }
  };

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          mb={2}
        >
          <Stack direction="row" alignItems="center" spacing={1}>
            <GitHubIcon fontSize="small" />
            <Typography variant="h6">GitHub Activity</Typography>
          </Stack>
          <Button variant="contained" onClick={() => setDialogOpen(true)}>
            Connect Repo
          </Button>
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Ingest recent commits, PRs, and issues from a GitHub repo into a
          folder. Metadata only — no source code. Used at session start to
          surface what changed in the repo since the last conversation.
        </Typography>

        {!loading && configs.length === 0 && (
          <Typography color="text.secondary">
            No GitHub integrations yet.
          </Typography>
        )}

        <Stack spacing={1.5}>
          {configs.map((cfg) => (
            <Box
              key={cfg.id}
              sx={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 2,
                p: 1.5,
                border: 1,
                borderColor: "divider",
                borderRadius: 1,
              }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography fontWeight="bold">
                  {cfg.repo_owner}/{cfg.repo_name}
                </Typography>
                <Typography variant="body2" color="text.secondary" noWrap>
                  Folder: {cfg.root_folder_name} · window {cfg.since_days}d
                  {cfg.last_synced_at
                    ? ` · last sync ${new Date(cfg.last_synced_at).toLocaleString()}`
                    : " · never synced"}
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
                sx={{
                  flexShrink: 0,
                  "& .MuiButton-root": { whiteSpace: "nowrap" },
                }}
              >
                <Button
                  startIcon={<RefreshIcon />}
                  onClick={() => handleSync(cfg.id)}
                  disabled={busyId === cfg.id}
                >
                  {busyId === cfg.id ? "Queued…" : "Sync now"}
                </Button>
                <Button
                  color="error"
                  startIcon={<DeleteIcon />}
                  onClick={() => setDisconnectTarget(cfg)}
                >
                  Disconnect
                </Button>
              </Stack>
            </Box>
          ))}
        </Stack>
      </CardContent>

      <GitHubConnectDialog
        open={dialogOpen}
        rootFolders={rootFolders}
        onClose={() => setDialogOpen(false)}
        onConnected={async () => {
          setDialogOpen(false);
          await refresh();
          toast.showSuccess("Connected. Trigger a sync to pull recent activity.");
        }}
      />

      <Dialog
        open={!!disconnectTarget}
        onClose={() => setDisconnectTarget(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Disconnect GitHub?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Disconnecting{" "}
            <strong>
              {disconnectTarget?.repo_owner}/{disconnectTarget?.repo_name}
            </strong>{" "}
            stops future syncs. Choose whether to keep the commit/PR/issue docs
            already ingested for this repo, or remove them.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ pr: 3, pb: 2 }}>
          <Button onClick={() => setDisconnectTarget(null)}>Cancel</Button>
          <Button onClick={() => handleDisconnect(false)}>Keep documents</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => handleDisconnect(true)}
          >
            Delete documents
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

export function GitHubConnectDialog({
  open,
  rootFolders,
  fixedFolderId,
  onClose,
  onConnected,
}: {
  open: boolean;
  rootFolders: Folder[];
  /** If provided, folder is locked and the picker is hidden. Used by the
   *  per-folder integrations dialog. */
  fixedFolderId?: string;
  onClose: () => void;
  onConnected: () => void;
}) {
  const [manualEntry, setManualEntry] = useState(false);
  const [repoUrl, setRepoUrl] = useState("");
  const [token, setToken] = useState("");
  const [repos, setRepos] = useState<GitHubRepoOption[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<GitHubRepoOption | null>(null);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [rootFolderId, setRootFolderId] = useState(fixedFolderId ?? "");
  const [sinceDays, setSinceDays] = useState(14);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const resetForm = () => {
    setManualEntry(false);
    setRepoUrl("");
    setToken("");
    setRepos([]);
    setSelectedRepo(null);
    setRootFolderId(fixedFolderId ?? "");
    setSinceDays(14);
    setError(null);
  };

  const loadRepos = async () => {
    setError(null);
    setLoadingRepos(true);
    try {
      const result = await listGitHubRepos(token);
      setRepos(result);
      if (result.length === 0) {
        setError("Token authenticated but returned no repos.");
      }
    } catch (err) {
      setError(`Couldn't list repos: ${messageFromError(err)}`);
    } finally {
      setLoadingRepos(false);
    }
  };

  const submit = async () => {
    setError(null);
    setBusy(true);
    const finalRepoUrl = selectedRepo ? selectedRepo.full_name : repoUrl;
    try {
      await connectGitHub({
        root_folder_id: rootFolderId,
        repo_url: finalRepoUrl,
        token: token || undefined,
        since_days: sinceDays,
      });
      onConnected();
      resetForm();
    } catch (err) {
      setError(`Couldn't connect: ${messageFromError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const canSubmit =
    !!rootFolderId &&
    (selectedRepo !== null || (manualEntry && !!repoUrl.trim())) &&
    !busy;

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Connect GitHub repository</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Provide a personal access token with <code>repo</code> scope, then
            pick a repo from the list. Read-only — we never write to your repo
            or clone code. Public-repo-only mode is available via "Enter URL
            manually".
          </Typography>
          <TextField
            label="GitHub token"
            placeholder="ghp_… or github_pat_…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            type="password"
            fullWidth
            autoFocus
          />

          {!manualEntry ? (
            <>
              <Stack direction="row" spacing={1} alignItems="center">
                <Button
                  variant="outlined"
                  onClick={loadRepos}
                  disabled={!token || loadingRepos}
                >
                  {loadingRepos ? "Loading…" : "Load my repos"}
                </Button>
                <Typography variant="caption" color="text.secondary">
                  or{" "}
                  <Button
                    size="small"
                    onClick={() => setManualEntry(true)}
                    sx={{ textTransform: "none", py: 0 }}
                  >
                    enter repo URL manually
                  </Button>
                </Typography>
              </Stack>

              {repos.length > 0 && (
                <Autocomplete
                  options={repos}
                  value={selectedRepo}
                  onChange={(_, v) => setSelectedRepo(v)}
                  getOptionLabel={(opt) => opt.full_name}
                  renderOption={(props, opt) => (
                    <Box component="li" {...props}>
                      <Stack sx={{ width: "100%" }}>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography sx={{ fontWeight: 600 }}>
                            {opt.full_name}
                          </Typography>
                          {opt.private && (
                            <Chip
                              label="private"
                              size="small"
                              sx={{ height: 18, fontSize: "0.65rem" }}
                            />
                          )}
                        </Stack>
                        {opt.description && (
                          <Typography variant="caption" color="text.secondary">
                            {opt.description}
                          </Typography>
                        )}
                        {opt.pushed_at && (
                          <Typography variant="caption" color="text.secondary">
                            pushed{" "}
                            {new Date(opt.pushed_at).toLocaleDateString()}
                          </Typography>
                        )}
                      </Stack>
                    </Box>
                  )}
                  renderInput={(params) => (
                    <TextField {...params} label={`Select repo (${repos.length})`} />
                  )}
                  fullWidth
                />
              )}
            </>
          ) : (
            <Stack spacing={1}>
              <TextField
                label="Repository URL or owner/repo"
                placeholder="https://github.com/owner/repo or owner/repo"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                fullWidth
              />
              <Button
                size="small"
                onClick={() => setManualEntry(false)}
                sx={{ alignSelf: "flex-start", textTransform: "none" }}
              >
                ← use the repo picker instead
              </Button>
            </Stack>
          )}

          {!fixedFolderId && (
            <FormControl fullWidth>
              <InputLabel>Root folder</InputLabel>
              <Select
                value={rootFolderId}
                label="Root folder"
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

          <TextField
            label="Look-back window (days)"
            type="number"
            value={sinceDays}
            onChange={(e) =>
              setSinceDays(Math.max(1, Math.min(365, Number(e.target.value))))
            }
            fullWidth
          />
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ pr: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={!canSubmit}>
          {busy ? "Verifying…" : "Connect"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
