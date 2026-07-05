import { useCallback, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
} from "@mui/material";
import { useNavigate, useLocation } from "react-router-dom";
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
  const { user, signOut } = useAuth();
  const {
    conversations,
    selectedId,
    selectConversation,
    createConversation,
    removeConversation,
  } = useConversationsContext();
  const [deleteTarget, setDeleteTarget] = useState<
    { id: string; name: string } | null
  >(null);
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
  // we just deleted (either /documents?folder=… or /folder/…).
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
      // Bounce the tree so it reflects the delete
      window.dispatchEvent(new CustomEvent("folders-changed"));
      // If we were viewing this folder, get out
      const search = new URLSearchParams(location.search);
      const viewingInDocuments =
        location.pathname === "/documents" &&
        search.get("folder") === deleteTarget.id;
      const viewingDetail = location.pathname === `/folder/${deleteTarget.id}`;
      if (viewingInDocuments) navigate("/documents");
      else if (viewingDetail) navigate("/documents");
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
    <Box sx={{ display: "flex", height: "100vh" }}>
      <IconRail
        activePage={activePage}
        onNavigate={(page) => navigate(page)}
        onTogglePanel={() => {}}
        userEmail={user?.email}
        onSignOut={signOut}
      />
      <ContextPanel
        activePage={activePage}
        open={showPanel}
        conversations={conversations}
        selectedConversationId={selectedId}
        onSelectConversation={selectConversation}
        onNewConversation={createConversation}
        onDeleteConversation={removeConversation}
        onNewFolder={handleNewFolder}
        onRequestDeleteFolder={handleRequestDeleteFolder}
      />
      <Box sx={{ flex: 1, overflow: "hidden" }}>{children}</Box>

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
            beneath it. This also removes any Mem0 / GitHub / Notion
            integrations wired to those folders.
          </DialogContentText>
          <DialogContentText>
            Choose whether to also delete the ingested documents (and their
            original files in storage), or keep the documents so they resurface
            at “All Documents”.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ pb: 2, pr: 3 }}>
          <Button
            onClick={() => setDeleteTarget(null)}
            disabled={busy}
          >
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
