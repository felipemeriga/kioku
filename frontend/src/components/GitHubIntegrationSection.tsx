import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
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
  syncGitHubNow,
} from "../lib/api";
import type { Folder, GitHubConfig } from "../lib/api";
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

function GitHubConnectDialog({
  open,
  rootFolders,
  onClose,
  onConnected,
}: {
  open: boolean;
  rootFolders: Folder[];
  onClose: () => void;
  onConnected: () => void;
}) {
  const [repoUrl, setRepoUrl] = useState("");
  const [token, setToken] = useState("");
  const [rootFolderId, setRootFolderId] = useState("");
  const [sinceDays, setSinceDays] = useState(14);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      await connectGitHub({
        root_folder_id: rootFolderId,
        repo_url: repoUrl,
        token: token || undefined,
        since_days: sinceDays,
      });
      onConnected();
      setRepoUrl("");
      setToken("");
      setRootFolderId("");
    } catch (err) {
      setError(`Couldn't connect: ${messageFromError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Connect GitHub repository</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Provide a repo URL and, for private repos, a personal access token
            with <code>repo</code> scope. Read-only — we never write to your
            repo or clone code.
          </Typography>
          <TextField
            label="Repository URL or owner/repo"
            placeholder="https://github.com/owner/repo or owner/repo"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            fullWidth
          />
          <TextField
            label="GitHub token (optional for public repos)"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            type="password"
            fullWidth
          />
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
        <Button
          variant="contained"
          onClick={submit}
          disabled={!repoUrl || !rootFolderId || busy}
        >
          {busy ? "Verifying…" : "Connect"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
