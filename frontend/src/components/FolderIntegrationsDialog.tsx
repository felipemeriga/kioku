/**
 * FolderIntegrationsDialog — manage a folder's integrations (Notion),
 * opened from the folder context menu.
 *
 * Mem0 memory is auto-on for repo folders and is now browsable via the
 * dedicated Mem0 tab on the repo page. Only Notion has a connect/sync/disconnect
 * flow here.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Stack,
  Typography,
} from "@mui/material";
import { NotionBrandIcon } from "./BrandIcons";
import RefreshIcon from "@mui/icons-material/Refresh";
import DeleteIcon from "@mui/icons-material/Delete";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { useNavigate } from "react-router-dom";
import {
  disconnectNotion,
  fetchNotionConfigs,
  syncNotionNow,
  type NotionConfig,
} from "../lib/api";
import { useToast } from "./ToastProvider";
import { NotionConnectDialog } from "./NotionIntegrationSection";
import CornerCard from "./neo/CornerCard";
import { brand, fonts, scanlines } from "../theme";

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
  const [notion, setNotion] = useState<NotionConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [notionConnectOpen, setNotionConnectOpen] = useState(false);

  const folderId = folder?.id ?? null;

  const refresh = useCallback(async () => {
    if (!folderId) return;
    setLoading(true);
    try {
      const n = await fetchNotionConfigs().catch(() => [] as NotionConfig[]);
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

  return (
    <>
      <Dialog
        open={open && !!folder}
        onClose={onClose}
        fullWidth
        maxWidth="sm"
        aria-label={folder ? `Integrations for ${folder.name}` : "Integrations"}
        slotProps={{
          paper: {
            sx: {
              position: "relative",
              overflow: "visible",
              border: `1px solid ${brand.magenta}`,
              borderRadius: 1,
              backgroundColor: brand.surface2,
              backgroundImage: scanlines,
              boxShadow: `0 0 4px ${brand.magenta}88, 0 0 24px ${brand.magenta}33, 0 24px 64px rgba(0,0,0,0.7)`,
              "&::before": {
                content: '""',
                position: "absolute",
                left: -1,
                top: -1,
                width: 12,
                height: 12,
                borderLeft: `2px solid ${brand.magenta}`,
                borderTop: `2px solid ${brand.magenta}`,
                pointerEvents: "none",
              },
              "&::after": {
                content: '""',
                position: "absolute",
                right: -1,
                bottom: -1,
                width: 12,
                height: 12,
                borderRight: `2px solid ${brand.magenta}`,
                borderBottom: `2px solid ${brand.magenta}`,
                pointerEvents: "none",
              },
            },
          },
        }}
      >
        <DialogTitle sx={{ fontSize: 21, fontWeight: 600, pb: 1 }}>
          Integrations for{" "}
          <Box
            component="span"
            sx={{
              color: brand.magentaGlow,
              textShadow: `0 0 10px ${brand.magenta}88`,
            }}
          >
            {folder?.name ?? ""}
          </Box>
        </DialogTitle>
        <DialogContent>
          <Typography
            variant="body2"
            sx={{ color: brand.muted, lineHeight: 1.55, mb: 2 }}
          >
            Wire this folder to Notion for note-sync. Mem0 memory is auto-on for
            repo folders and is browsable via the Mem0 tab on the repo page.
          </Typography>

          <Stack spacing={2}>
            {/* Notion section */}
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
            sx={{
              textTransform: "none",
              fontWeight: 600,
              fontSize: 14,
              color: brand.magentaGlow,
              "&:hover": { color: brand.text, background: "transparent" },
            }}
            disableRipple
          >
            Open folder detail
          </Button>
          <Button
            onClick={onClose}
            sx={{
              height: 34,
              px: "14px",
              borderRadius: "4px",
              border: `1px solid ${brand.lineGlow}`,
              background: "transparent",
              color: brand.text,
              fontWeight: 600,
              fontSize: 13,
              textTransform: "none",
              "&:hover": {
                borderColor: brand.magenta,
                background: "transparent",
              },
            }}
          >
            Close
          </Button>
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
  cardColor,
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
  cardColor?: string;
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
  const color = cardColor ?? brand.line;

  return (
    <CornerCard
      color={color}
      sx={{
        display: "flex",
        flexDirection: "column",
        gap: 1,
        p: "16px 18px",
        opacity: loading ? 0.6 : 1,
      }}
    >
      {/* Header row */}
      <Stack direction="row" alignItems="center" spacing={1.25}>
        <Box sx={{ color: brand.muted, display: "flex", alignItems: "center" }}>
          {icon}
        </Box>
        <Typography
          component="h2"
          sx={{ m: 0, fontSize: 16, fontWeight: 600, flex: 1 }}
        >
          {title}
        </Typography>

        {connected ? (
          /* "On" badge with green glow */
          <Box
            component="span"
            sx={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              px: "10px",
              py: "3px",
              borderRadius: "3px",
              border: `1px solid ${brand.green}`,
              background: `${brand.green}18`,
              color: brand.green,
              fontFamily: fonts.mono,
              fontSize: 12,
              boxShadow: `0 0 10px ${brand.green}44`,
            }}
          >
            <Box
              component="span"
              sx={{
                width: 7,
                height: 7,
                borderRadius: "999px",
                background: brand.green,
                boxShadow: `0 0 6px ${brand.green}`,
                display: "inline-block",
              }}
            />
            {connectedLabel}
          </Box>
        ) : (
          /* "Not connected" badge */
          <Box
            component="span"
            sx={{
              px: "10px",
              py: "3px",
              borderRadius: "3px",
              border: `1px solid ${brand.lineGlow}`,
              color: brand.muted,
              fontFamily: fonts.mono,
              fontSize: 12,
            }}
          >
            {disconnectedLabel === "Repo-only"
              ? disconnectedLabel
              : `⊘ ${disconnectedLabel}`}
          </Box>
        )}
      </Stack>

      {/* Description */}
      <Typography variant="body2" sx={{ color: brand.muted }}>
        {description}
      </Typography>

      {/* Status detail */}
      {statusDetail && (
        <Typography
          variant="caption"
          sx={{
            display: "block",
            color: brand.muted,
            fontFamily: fonts.mono,
            fontSize: 12,
          }}
        >
          {statusDetail}
        </Typography>
      )}

      {/* Error */}
      {errorDetail && (
        <Alert severity="warning" sx={{ mt: 0.5 }}>
          {errorDetail}
        </Alert>
      )}

      {/* Disconnected hint */}
      {!connected && disconnectedHint && (
        <Typography variant="caption" sx={{ color: brand.muted }}>
          {disconnectedHint}
        </Typography>
      )}

      {/* Actions */}
      {showActions && (
        <>
          <Divider sx={{ borderColor: brand.line, my: 0.5 }} />
          <Stack direction="row" spacing={1} justifyContent="flex-end">
            {!connected && onConnect && (
              <Button
                size="small"
                onClick={onConnect}
                sx={{
                  height: 36,
                  px: "16px",
                  border: 0,
                  borderRadius: "4px",
                  backgroundImage: `linear-gradient(90deg, ${brand.magentaDeep} 0%, ${brand.purple} 100%)`,
                  color: "#fff",
                  fontWeight: 600,
                  fontSize: 13,
                  textTransform: "none",
                  boxShadow: `0 4px 12px ${brand.magenta}44`,
                  "&:hover": {
                    backgroundImage: `linear-gradient(90deg, ${brand.magenta} 0%, ${brand.purple} 100%)`,
                    boxShadow: `0 4px 16px ${brand.magenta}66`,
                  },
                }}
              >
                Connect
              </Button>
            )}
            {connected && onSync && (
              <Button
                size="small"
                startIcon={<RefreshIcon />}
                onClick={onSync}
                sx={{
                  textTransform: "none",
                  color: brand.muted,
                  fontSize: 13,
                  "&:hover": { color: brand.text },
                }}
              >
                Sync now
              </Button>
            )}
            {connected && onDisconnect && (
              <Button
                size="small"
                startIcon={<DeleteIcon />}
                onClick={onDisconnect}
                sx={{
                  textTransform: "none",
                  color: brand.muted,
                  fontSize: 13,
                  "&:hover": { color: brand.red },
                }}
              >
                Disconnect
              </Button>
            )}
          </Stack>
        </>
      )}
    </CornerCard>
  );
}
