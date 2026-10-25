import { useCallback, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Drawer,
  IconButton,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { useNavigate, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import MenuOpenIcon from "@mui/icons-material/MenuOpen";
import { brand } from "../theme";
import NeoAtmosphere from "./neo/NeoAtmosphere";
import IconRail, { type AppPage } from "./IconRail";
import ContextPanel from "./ContextPanel";
import { useAuth } from "../hooks/useAuth";
import { useConversationsContext } from "../hooks/useConversationsContext";
import { deleteFolder } from "../lib/api";
import { messageFromError, useToast } from "./ToastProvider";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { user, signOut } = useAuth();
  const {
    conversations,
    conversationsLoading,
    conversationsError,
    loadConversations,
    selectedId,
    selectConversation,
    createConversation,
    removeConversation,
  } = useConversationsContext();
  const [deleteTarget, setDeleteTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const mobile = useMediaQuery(useTheme().breakpoints.down("md"));
  const [panelOpen, setPanelOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const activePage = (location.pathname as AppPage) || "/";

  // Show panel on pages that have contextual content
  const showPanel = activePage === "/" || activePage === "/documents";

  const handleNewFolder = useCallback(() => {
    window.dispatchEvent(new CustomEvent("new-folder"));
  }, []);

  // Sidebar folder trash-icon path. Previously fell through to a no-op
  // because AppLayout never wired onRequestDeleteFolder — the ContextPanel
  // used optional chaining and swallowed the call. Now: open a confirmation
  // dialog with the same delete_docs choice as the Documents-page delete
  // flow, then navigate away if the user is currently viewing the folder
  // we just deleted (/documents?folder=…).
  const handleRequestDeleteFolder = useCallback(
    (folderId: string, folderName: string) => {
      setDeleteTarget({ id: folderId, name: folderName });
    },
    []
  );

  const doDelete = async (deleteDocs: boolean) => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await deleteFolder(deleteTarget.id, deleteDocs);
      // Refresh every folder list (sidebar tree + grid + dialogs).
      queryClient.invalidateQueries({ queryKey: ["folders"] });
      // If we were viewing this folder, get out
      const search = new URLSearchParams(location.search);
      const viewingInDocuments =
        location.pathname === "/documents" &&
        search.get("folder") === deleteTarget.id;
      if (viewingInDocuments) navigate("/documents");
      toast.showSuccess(
        deleteDocs
          ? `Deleted “${deleteTarget.name}” and its documents.`
          : `Deleted “${deleteTarget.name}”. Documents kept.`
      );
      setDeleteTarget(null);
    } catch (err) {
      toast.showError(err, `Couldn't delete: ${messageFromError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box
      sx={{
        display: "flex",
        height: "100dvh",
        overflow: "hidden",
        "@media(max-width:480px)": { flexDirection: "column" },
      }}
    >
      <IconRail
        activePage={activePage}
        onNavigate={(page) => navigate(page)}
        onTogglePanel={() => setPanelOpen((value) => !value)}
        userEmail={user?.email}
        onSignOut={signOut}
      />
      {!mobile && (
        <ContextPanel
          activePage={activePage}
          open={showPanel}
          conversations={conversations}
          conversationsLoading={conversationsLoading}
          conversationsError={conversationsError}
          onRetryConversations={() => void loadConversations?.()}
          selectedConversationId={selectedId}
          onSelectConversation={selectConversation}
          onNewConversation={() =>
            void createConversation().catch((err) =>
              toast.showError(err, "Couldn’t create conversation.")
            )
          }
          onDeleteConversation={removeConversation}
          onNewFolder={handleNewFolder}
          onRequestDeleteFolder={handleRequestDeleteFolder}
        />
      )}
      <Drawer
        open={mobile && panelOpen && showPanel}
        onClose={() => setPanelOpen(false)}
      >
        <Box
          sx={{ width: 280 }}
          onClick={(event) => {
            if (
              (event.target as HTMLElement).closest("[data-folder-navigation]")
            )
              setPanelOpen(false);
          }}
        >
          <ContextPanel
            activePage={activePage}
            open={showPanel}
            conversations={conversations}
            conversationsLoading={conversationsLoading}
            conversationsError={conversationsError}
            onRetryConversations={() => void loadConversations?.()}
            selectedConversationId={selectedId}
            onSelectConversation={selectConversation}
            onNewConversation={() =>
              void createConversation().catch((err) =>
                toast.showError(err, "Couldn’t create conversation.")
              )
            }
            onDeleteConversation={removeConversation}
            onNewFolder={handleNewFolder}
            onRequestDeleteFolder={handleRequestDeleteFolder}
          />
        </Box>
      </Drawer>
      <Box
        component="main"
        id="main-content"
        sx={{
          flex: 1,
          position: "relative",
          isolation: "isolate",
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          overflowY: "auto",
          overflowX: "hidden",
        }}
      >
        <NeoAtmosphere />
        <Box
          component="header"
          data-testid="app-topbar"
          sx={{
            minHeight: 70,
            height: 70,
            flexShrink: 0,
            px: "40px",
            display: "flex",
            alignItems: "center",
            gap: 1.5,
            borderBottom: `1px solid ${brand.line}`,
            "@media(max-width:780px)": { px: "22px" },
            "@media(max-width:480px)": {
              px: "18px",
              minHeight: 53,
              height: 53,
            },
          }}
        >
          {mobile && showPanel && (
            <IconButton
              aria-label={
                activePage === "/documents"
                  ? "Open folder navigator"
                  : "Open conversations"
              }
              onClick={() => setPanelOpen(true)}
              size="small"
            >
              <MenuOpenIcon fontSize="small" />
            </IconButton>
          )}
          <Typography sx={{ color: brand.muted, fontSize: 13 }}>
            Kioku{" "}
            <Box component="span" sx={{ px: 1, color: brand.dim }}>
              /
            </Box>{" "}
            <Box component="span" sx={{ color: brand.text }}>
              {activePage === "/"
                ? "Chat"
                : activePage === "/documents"
                ? "Documents"
                : activePage === "/remotes"
                ? "Remotes"
                : "Settings"}
            </Box>
          </Typography>
        </Box>
        {children}
      </Box>

      <Dialog
        open={!!deleteTarget}
        onClose={() => !busy && setDeleteTarget(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Delete folder?</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 1 }}>
            Delete <strong>{deleteTarget?.name}</strong> and every subfolder
            beneath it. This also removes any GitHub / Notion integrations wired
            to those folders.
          </DialogContentText>
          <DialogContentText>
            Choose whether to also delete the ingested documents (and their
            original files in storage), or keep the documents so they resurface
            at “All Documents”.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ pb: 2, pr: 3 }}>
          <Button onClick={() => setDeleteTarget(null)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void doDelete(false)} disabled={busy}>
            Keep documents
          </Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => void doDelete(true)}
            disabled={busy}
          >
            {busy ? "Deleting…" : "Delete documents"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
