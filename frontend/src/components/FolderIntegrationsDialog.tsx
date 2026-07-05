/**
 * FolderIntegrationsDialog — one dialog to manage all three integrations
 * (Mem0, Notion, GitHub) for a specific folder, opened from the folder
 * context menu. Reuses the existing connect dialogs, pre-scoped to this folder.
 *
 * Layout: three cards, one per integration. Each card shows connection status,
 * and offers connect / sync / disconnect actions inline.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  Typography,
} from "@mui/material";
import PsychologyIcon from "@mui/icons-material/Psychology";
import GitHubIcon from "@mui/icons-material/GitHub";
import NotesIcon from "@mui/icons-material/Notes";
import RefreshIcon from "@mui/icons-material/Refresh";
import DeleteIcon from "@mui/icons-material/Delete";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import LinkOffIcon from "@mui/icons-material/LinkOff";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useNavigate } from "react-router-dom";
import {
  disconnectGitHub,
  disconnectMem0,
  disconnectNotion,
  fetchGitHubConfigs,
  fetchMem0Configs,
  fetchNotionConfigs,
  syncGitHubNow,
  syncNotionNow,
  type Folder,
  type GitHubConfig,
  type Mem0Config,
  type NotionConfig,
} from "../lib/api";
import { messageFromError, useToast } from "./ToastProvider";
import { Mem0ConnectDialog } from "./Mem0IntegrationSection";
import { GitHubConnectDialog } from "./GitHubIntegrationSection";
import { NotionConnectDialog } from "./NotionIntegrationSection";

interface Props {
  open: boolean;
  folder: { id: string; name: string; kind?: "folder" | "repo" } | null;
  onClose: () => void;
}

type IntegrationKey = "mem0" | "notion" | "github";

export default function FolderIntegrationsDialog({
  open,
  folder,
  onClose,
}: Props) {
  const toast = useToast();
  const navigate = useNavigate();
  const [mem0, setMem0] = useState<Mem0Config | null>(null);
  const [notion, setNotion] = useState<NotionConfig | null>(null);
  const [github, setGithub] = useState<GitHubConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [connectOpen, setConnectOpen] = useState<IntegrationKey | null>(null);

  const folderId = folder?.id ?? null;
  const fakeRootFolders: Folder[] = useMemo(
    () =>
      folder
        ? [
            {
              id: folder.id,
              name: folder.name,
              parent_id: null,
              user_id: "",
              created_at: "",
            } as Folder,
          ]
        : [],
    [folder]
  );

  const refresh = useCallback(async () => {
    if (!folderId) return;
    setLoading(true);
    try {
      const [m, n, g] = await Promise.all([
        fetchMem0Configs().catch(() => [] as Mem0Config[]),
        fetchNotionConfigs().catch(() => [] as NotionConfig[]),
        fetchGitHubConfigs().catch(() => [] as GitHubConfig[]),
      ]);
      setMem0(m.find((c) => c.root_folder_id === folderId) ?? null);
      setNotion(n.find((c) => c.root_folder_id === folderId) ?? null);
      setGithub(g.find((c) => c.root_folder_id === folderId) ?? null);
    } catch (err) {
      toast.showError(err, "Couldn't load integrations.");
    } finally {
      setLoading(false);
    }
  }, [folderId, toast]);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  // ── Actions ────────────────────────────────────────────────────────────
  const handleDisconnect = async (kind: IntegrationKey) => {
    try {
      if (kind === "mem0" && mem0) await disconnectMem0(mem0.id);
      if (kind === "github" && github) await disconnectGitHub(github.id, false);
      if (kind === "notion" && notion) await disconnectNotion(notion.id, false);
      await refresh();
      toast.showSuccess(`${kind} disconnected.`);
    } catch (err) {
      toast.showError(err, `Couldn't disconnect ${kind}.`);
    }
  };

  const handleSync = async (kind: IntegrationKey) => {
    try {
      if (kind === "github" && github) {
        await syncGitHubNow(github.id);
        toast.showSuccess("GitHub sync queued.");
      } else if (kind === "notion" && notion) {
        await syncNotionNow(notion.id);
        toast.showSuccess("Notion sync queued.");
      }
    } catch (err) {
      toast.showError(err, `Couldn't sync ${kind}.`);
    }
  };

  return (
    <>
      <Dialog open={open && !!folder} onClose={onClose} fullWidth maxWidth="sm">
        <DialogTitle>
          Integrations for{" "}
          <Box component="span" sx={{ color: "primary.main", fontWeight: 600 }}>
            {folder?.name ?? ""}
          </Box>
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Wire this folder to memory, note-sync, and repo activity sources.
            None of these are required — leave any of them disconnected and
            they simply won't appear in the folder orientation.
          </Typography>

          <Stack spacing={2}>
            {/* Mem0 is repo-only. On a plain folder we still show the card
                but disable Connect and add a hint explaining why. */}
            <IntegrationCard
              icon={<PsychologyIcon fontSize="small" />}
              title="Mem0 memory"
              description="Episodic and eternal memory (agent-authored) scoped to this repo."
              connected={!!mem0}
              statusDetail={
                mem0?.last_verified_at
                  ? `Verified ${new Date(
                      mem0.last_verified_at
                    ).toLocaleString()}`
                  : mem0
                  ? "Never verified"
                  : null
              }
              errorDetail={mem0?.last_error ?? null}
              onConnect={
                folder?.kind === "repo" ? () => setConnectOpen("mem0") : undefined
              }
              onDisconnect={mem0 ? () => handleDisconnect("mem0") : undefined}
              loading={loading}
              connectHint={
                folder?.kind === "repo"
                  ? undefined
                  : "Mem0 is repo-only — connect this folder to a GitHub repo first."
              }
            />

            <IntegrationCard
              icon={<NotesIcon fontSize="small" />}
              title="Notion sync"
              description="Ingest a Notion root page as documents. Fast poll + full reconciliation."
              connected={!!notion}
              statusDetail={
                notion?.last_fast_sync_at
                  ? `Last fast sync ${new Date(
                      notion.last_fast_sync_at
                    ).toLocaleString()}`
                  : notion
                  ? "Never synced"
                  : null
              }
              errorDetail={notion?.last_error ?? null}
              onConnect={() => setConnectOpen("notion")}
              onSync={notion ? () => handleSync("notion") : undefined}
              onDisconnect={() => handleDisconnect("notion")}
              loading={loading}
            />

            <IntegrationCard
              icon={<GitHubIcon fontSize="small" />}
              title="GitHub activity"
              description="Recent commits, PRs, and issues from a GitHub repo — metadata only."
              connected={!!github}
              statusDetail={
                github
                  ? `${github.repo_owner}/${github.repo_name}` +
                    (github.last_synced_at
                      ? ` · last sync ${new Date(
                          github.last_synced_at
                        ).toLocaleString()}`
                      : " · never synced")
                  : null
              }
              errorDetail={github?.last_error ?? null}
              onConnect={() => setConnectOpen("github")}
              onSync={github ? () => handleSync("github") : undefined}
              onDisconnect={() => handleDisconnect("github")}
              loading={loading}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ justifyContent: "space-between", px: 3, pb: 2 }}>
          <Button
            onClick={() => {
              if (folder) {
                onClose();
                navigate(`/folder/${folder.id}`);
              }
            }}
            startIcon={<OpenInNewIcon fontSize="small" />}
            sx={{ textTransform: "none" }}
          >
            Open folder detail
          </Button>
          <Button onClick={onClose}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Reused connect dialogs, pre-scoped to this folder. */}
      {folder && (
        <>
          <Mem0ConnectDialog
            open={connectOpen === "mem0"}
            rootFolders={fakeRootFolders}
            fixedFolderId={folder.id}
            onClose={() => setConnectOpen(null)}
            onConnected={async () => {
              setConnectOpen(null);
              await refresh();
              toast.showSuccess("Mem0 connected.");
            }}
          />
          <GitHubConnectDialog
            open={connectOpen === "github"}
            rootFolders={fakeRootFolders}
            fixedFolderId={folder.id}
            onClose={() => setConnectOpen(null)}
            onConnected={async () => {
              setConnectOpen(null);
              await refresh();
              toast.showSuccess("GitHub connected.");
            }}
          />
          <NotionConnectDialog
            open={connectOpen === "notion"}
            rootFolders={[{ id: folder.id, name: folder.name }]}
            fixedFolderId={folder.id}
            onClose={() => setConnectOpen(null)}
            onConnected={async () => {
              setConnectOpen(null);
              await refresh();
              toast.showSuccess("Notion connected.");
            }}
          />
        </>
      )}
    </>
  );
}

function IntegrationCard({
  icon,
  title,
  description,
  connected,
  statusDetail,
  errorDetail,
  connectHint,
  onConnect,
  onSync,
  onDisconnect,
  loading,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  connected: boolean;
  statusDetail: string | null;
  errorDetail: string | null;
  connectHint?: string;
  onConnect?: () => void;
  onSync?: () => void;
  onDisconnect?: () => void;
  loading: boolean;
}) {
  return (
    <Box
      sx={{
        border: 1,
        borderColor: "divider",
        borderRadius: 1.5,
        p: 2,
        opacity: loading ? 0.6 : 1,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1 }}>
        {icon}
        <Typography variant="subtitle1" sx={{ fontWeight: 600, flex: 1 }}>
          {title}
        </Typography>
        <Chip
          size="small"
          icon={connected ? <CheckCircleIcon /> : <LinkOffIcon />}
          label={connected ? "Connected" : "Not connected"}
          color={connected ? "success" : "default"}
          variant={connected ? "filled" : "outlined"}
          sx={{ fontSize: "0.7rem", height: 22 }}
        />
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {description}
      </Typography>

      {statusDetail && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
          {statusDetail}
        </Typography>
      )}

      {errorDetail && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {errorDetail}
        </Alert>
      )}

      <Divider sx={{ my: 1.5 }} />
      <Stack direction="row" spacing={1} justifyContent="flex-end">
        {!connected && onConnect && (
          <Button size="small" variant="contained" onClick={onConnect}>
            Connect
          </Button>
        )}
        {!connected && !onConnect && connectHint && (
          <Typography variant="caption" color="text.secondary">
            {connectHint}
          </Typography>
        )}
        {connected && onSync && (
          <Button size="small" startIcon={<RefreshIcon />} onClick={onSync}>
            Sync now
          </Button>
        )}
        {connected && onDisconnect && (
          <Button
            size="small"
            color="error"
            startIcon={<DeleteIcon />}
            onClick={onDisconnect}
          >
            Disconnect
          </Button>
        )}
      </Stack>
    </Box>
  );
}
