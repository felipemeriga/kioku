/**
 * FolderIntegrationsDialog — manage a folder's integrations (Mem0, Notion),
 * opened from the folder context menu.
 *
 * Mem0 memory is auto-on for repo folders (self-hosted, no connect step), so
 * its card is status-only. Notion still has a connect/sync/disconnect flow.
 */

import { useCallback, useEffect, useState } from "react";
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
import { Mem0BrandIcon, NotionBrandIcon } from "./BrandIcons";
import RefreshIcon from "@mui/icons-material/Refresh";
import DeleteIcon from "@mui/icons-material/Delete";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import LinkOffIcon from "@mui/icons-material/LinkOff";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useNavigate } from "react-router-dom";
import {
  disconnectNotion,
  fetchMem0Status,
  fetchNotionConfigs,
  syncNotionNow,
  type Mem0Status,
  type NotionConfig,
} from "../lib/api";
import { useToast } from "./ToastProvider";
import { NotionConnectDialog } from "./NotionIntegrationSection";

interface Props {
  open: boolean;
  folder: { id: string; name: string; kind?: "folder" | "repo" } | null;
  onClose: () => void;
}

export default function FolderIntegrationsDialog({
  open,
  folder,
  onClose,
}: Props) {
  const toast = useToast();
  const navigate = useNavigate();
  const [mem0Status, setMem0Status] = useState<Mem0Status | null>(null);
  const [notion, setNotion] = useState<NotionConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [notionConnectOpen, setNotionConnectOpen] = useState(false);

  const folderId = folder?.id ?? null;

  const refresh = useCallback(async () => {
    if (!folderId) return;
    setLoading(true);
    try {
      const [ms, n] = await Promise.all([
        fetchMem0Status(folderId).catch(() => null),
        fetchNotionConfigs().catch(() => [] as NotionConfig[]),
      ]);
      setMem0Status(ms);
      setNotion(n.find((c) => c.root_folder_id === folderId) ?? null);
    } catch (err) {
      toast.showError(err, "Couldn't load integrations.");
    } finally {
      setLoading(false);
    }
  }, [folderId, toast]);

  useEffect(() => {
    if (open) void refresh();
  }, [open, refresh]);

  const handleDisconnectNotion = async () => {
    if (!notion) return;
    try {
      await disconnectNotion(notion.id, false);
      await refresh();
      toast.showSuccess("Notion disconnected.");
    } catch (err) {
      toast.showError(err, "Couldn't disconnect Notion.");
    }
  };

  const handleSyncNotion = async () => {
    if (!notion) return;
    try {
      await syncNotionNow(notion.id);
      toast.showSuccess("Notion sync queued.");
    } catch (err) {
      toast.showError(err, "Couldn't sync Notion.");
    }
  };

  const memAvailable = !!mem0Status?.available;

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
            Wire this folder to memory and note-sync. None are required — leave
            them off and they simply won't appear in the folder orientation.
          </Typography>

          <Stack spacing={2}>
            {/* Mem0 is self-hosted and auto-on for repo folders — no connect. */}
            <IntegrationCard
              icon={<Mem0BrandIcon fontSize="small" />}
              title="Mem0 memory"
              description="Episodic + eternal memory (agent-authored), scoped to this repo."
              connected={memAvailable}
              connectedLabel="On"
              disconnectedLabel="Repo-only"
              statusDetail={
                memAvailable
                  ? mem0Status?.healthy
                    ? "On automatically · memory service healthy"
                    : "On · memory service unreachable"
                  : null
              }
              errorDetail={
                memAvailable && mem0Status?.healthy === false
                  ? mem0Status?.error ?? "Memory service is unreachable."
                  : null
              }
              disconnectedHint={
                !memAvailable
                  ? "Auto-on for repo folders — run `kioku init` here to make this a repo and enable memory."
                  : undefined
              }
              loading={loading}
            />

            <IntegrationCard
              icon={<NotionBrandIcon fontSize="small" />}
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
              onConnect={() => setNotionConnectOpen(true)}
              onSync={notion ? handleSyncNotion : undefined}
              onDisconnect={notion ? handleDisconnectNotion : undefined}
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

      {folder && (
        <NotionConnectDialog
          open={notionConnectOpen}
          rootFolders={[{ id: folder.id, name: folder.name }]}
          fixedFolderId={folder.id}
          onClose={() => setNotionConnectOpen(false)}
          onConnected={async () => {
            setNotionConnectOpen(false);
            await refresh();
            toast.showSuccess("Notion connected.");
          }}
        />
      )}
    </>
  );
}

function IntegrationCard({
  icon,
  title,
  description,
  connected,
  connectedLabel = "Connected",
  disconnectedLabel = "Not connected",
  statusDetail,
  errorDetail,
  disconnectedHint,
  onConnect,
  onSync,
  onDisconnect,
  loading,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  connected: boolean;
  connectedLabel?: string;
  disconnectedLabel?: string;
  statusDetail: string | null;
  errorDetail: string | null;
  disconnectedHint?: string;
  onConnect?: () => void;
  onSync?: () => void;
  onDisconnect?: () => void;
  loading: boolean;
}) {
  const showActions =
    (!connected && !!onConnect) || (connected && (!!onSync || !!onDisconnect));
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
          label={connected ? connectedLabel : disconnectedLabel}
          color={connected ? "success" : "default"}
          variant={connected ? "filled" : "outlined"}
          sx={{ fontSize: "0.7rem", height: 22 }}
        />
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {description}
      </Typography>

      {statusDetail && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mb: 1 }}
        >
          {statusDetail}
        </Typography>
      )}

      {errorDetail && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {errorDetail}
        </Alert>
      )}

      {!connected && disconnectedHint && (
        <Typography variant="caption" color="text.secondary">
          {disconnectedHint}
        </Typography>
      )}

      {showActions && (
        <>
          <Divider sx={{ my: 1.5 }} />
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            {!connected && onConnect && (
              <Button size="small" variant="contained" onClick={onConnect}>
                Connect
              </Button>
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
        </>
      )}
    </Box>
  );
}
