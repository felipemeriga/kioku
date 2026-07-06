import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  InputBase,
  List,
  ListItemButton,
  ListItemText,
  ListItemIcon,
  IconButton,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import { useSearchParams } from "react-router-dom";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import EditIcon from "@mui/icons-material/Edit";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import FolderTree from "./FolderTree";
import FolderIntegrationsDialog from "./FolderIntegrationsDialog";
import { renameConversation } from "../lib/api";
import { messageFromError, useToast } from "./ToastProvider";
import type { AppPage } from "./IconRail";
import type { Conversation } from "../lib/api";

interface ContextPanelProps {
  activePage: AppPage;
  open: boolean;
  conversations: Conversation[];
  selectedConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onDeleteConversation: (id: string) => void;
  onRequestDeleteFolder?: (folderId: string, folderName: string) => void;
  onNewFolder?: () => void;
}

export default function ContextPanel({
  activePage,
  open,
  conversations,
  selectedConversationId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onRequestDeleteFolder,
  onNewFolder,
}: ContextPanelProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  const selectedFolderId = searchParams.get("folder") || null;

  const handleSelectFolder = useCallback(
    (id: string | null) => {
      setSearchParams(id ? { folder: id } : {}, { replace: true });
    },
    [setSearchParams]
  );

  const handleDeleteFolder = useCallback(
    (folderId: string, folderName: string) => {
      onRequestDeleteFolder?.(folderId, folderName);
    },
    [onRequestDeleteFolder]
  );

  const [integrationsTarget, setIntegrationsTarget] = useState<
    { id: string; name: string } | null
  >(null);
  const handleRequestIntegrations = useCallback(
    (folderId: string, folderName: string) => {
      setIntegrationsTarget({ id: folderId, name: folderName });
    },
    []
  );

  if (!open) return null;

  return (
    <Box
      data-testid="context-panel"
      sx={{
        width: 220,
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        bgcolor: alpha("#121219", 0.8),
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderRight: 1,
        borderColor: "divider",
        flexShrink: 0,
      }}
    >
      {activePage === "/" && (
        <ChatPanel
          conversations={conversations}
          selectedId={selectedConversationId}
          onSelect={onSelectConversation}
          onNew={onNewConversation}
          onDelete={onDeleteConversation}
        />
      )}
      {/* rename handled inside ChatPanel via the api layer directly */}
      {activePage === "/documents" && (
        <>
          <Box
            sx={{
              px: 1.5,
              pt: 1.5,
              pb: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Typography
              variant="caption"
              sx={{
                color: alpha("#ffffff", 0.3),
                letterSpacing: 1,
                textTransform: "uppercase",
                fontSize: "0.65rem",
                pl: 0.5,
              }}
            >
              Folders
            </Typography>
            {onNewFolder && (
              <IconButton
                size="small"
                onClick={onNewFolder}
                sx={{
                  width: 24,
                  height: 24,
                  borderRadius: 1,
                  bgcolor: alpha("#FF2E93", 0.15),
                  color: "#a78bfa",
                  "&:hover": { bgcolor: alpha("#FF2E93", 0.25) },
                }}
              >
                <AddIcon sx={{ fontSize: 14 }} />
              </IconButton>
            )}
          </Box>
          <Box sx={{ flex: 1, overflow: "auto" }}>
            <FolderTree
              selectedFolderId={selectedFolderId}
              onSelectFolder={handleSelectFolder}
              onRequestDelete={handleDeleteFolder}
              onRequestIntegrations={handleRequestIntegrations}
            />
          </Box>
          <FolderIntegrationsDialog
            open={!!integrationsTarget}
            folder={integrationsTarget}
            onClose={() => setIntegrationsTarget(null)}
          />
        </>
      )}
    </Box>
  );
}

function ChatPanel({
  conversations,
  selectedId,
  onSelect,
  onNew,
  onDelete,
}: {
  conversations: Conversation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <>
      <Box
        sx={{
          px: 1.5,
          pt: 1.5,
          pb: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Typography
          variant="caption"
          sx={{
            color: alpha("#ffffff", 0.3),
            letterSpacing: 1,
            textTransform: "uppercase",
            fontSize: "0.65rem",
            pl: 0.5,
          }}
        >
          Conversations
        </Typography>
        <IconButton
          data-testid="new-chat-button"
          size="small"
          onClick={onNew}
          sx={{
            width: 24,
            height: 24,
            borderRadius: 1,
            bgcolor: alpha("#FF2E93", 0.15),
            color: "#a78bfa",
            "&:hover": { bgcolor: alpha("#FF2E93", 0.25) },
          }}
        >
          <AddIcon sx={{ fontSize: 14 }} />
        </IconButton>
      </Box>

      <List sx={{ flex: 1, overflow: "auto", px: 0.5 }}>
        {conversations.map((conv) => (
          <ConversationRow
            key={conv.id}
            conv={conv}
            isSelected={conv.id === selectedId}
            onSelect={() => onSelect(conv.id)}
            onDelete={() => onDelete(conv.id)}
          />
        ))}
      </List>
    </>
  );
}

/**
 * One conversation in the sidebar list. Hover reveals rename + delete
 * icons; clicking rename swaps the title for an inline InputBase. Enter
 * saves, Escape reverts. Double-clicking the title also enters edit mode
 * (more discoverable than the pencil for keyboard-fluent users).
 */
function ConversationRow({
  conv,
  isSelected,
  onSelect,
  onDelete,
}: {
  conv: Conversation;
  isSelected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conv.title);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Keep local state in sync when the row's underlying title changes
  // (e.g. the server assigns a title from the first message).
  useEffect(() => {
    if (!editing) setDraft(conv.title);
  }, [conv.title, editing]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setDraft(conv.title);
    setEditing(true);
  };

  const commit = async () => {
    const next = draft.trim();
    if (!next || next === conv.title) {
      setEditing(false);
      setDraft(conv.title);
      return;
    }
    setSaving(true);
    try {
      await renameConversation(conv.id, next);
      // Nudge the sidebar to reload; the conversations list is refreshed via
      // the existing 'conversations-changed' listener + parent refetch.
      window.dispatchEvent(new CustomEvent("conversations-changed"));
      setEditing(false);
    } catch (err) {
      toast.showError(err, `Couldn't rename: ${messageFromError(err)}`);
      setDraft(conv.title);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    setDraft(conv.title);
    setEditing(false);
  };

  return (
    <ListItemButton
      selected={isSelected}
      onClick={editing ? undefined : onSelect}
      onDoubleClick={(e) => startEdit(e)}
      sx={{
        borderRadius: 1.5,
        mx: 0.5,
        py: 0.6,
        mb: 0.25,
        "&.Mui-selected": {
          bgcolor: alpha("#FF2E93", 0.12),
          "&:hover": { bgcolor: alpha("#FF2E93", 0.18) },
        },
        "&:hover": {
          bgcolor: alpha("#ffffff", 0.04),
          "& .conv-actions": { opacity: 1 },
        },
      }}
    >
      <ListItemIcon sx={{ minWidth: 28 }}>
        <ChatBubbleOutlineIcon
          sx={{ fontSize: 15, color: alpha("#ffffff", 0.3) }}
        />
      </ListItemIcon>
      {editing ? (
        <InputBase
          inputRef={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void commit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              cancel();
            }
          }}
          onBlur={() => void commit()}
          disabled={saving}
          fullWidth
          sx={{
            fontSize: "0.85rem",
            color: "#fff",
            "& input": {
              padding: 0,
              border: `1px solid ${alpha("#FF2E93", 0.4)}`,
              borderRadius: 0.75,
              px: 1,
              py: 0.4,
              bgcolor: alpha("#FF2E93", 0.08),
            },
          }}
        />
      ) : (
        <>
          <ListItemText
            primary={conv.title}
            primaryTypographyProps={{
              noWrap: true,
              variant: "body2",
              sx: { fontWeight: isSelected ? 500 : 400 },
            }}
          />
          <Box
            className="conv-actions"
            sx={{
              display: "flex",
              alignItems: "center",
              opacity: 0,
              transition: "opacity 0.15s",
              gap: 0.25,
            }}
          >
            <Tooltip title="Rename">
              <IconButton
                size="small"
                aria-label="Rename conversation"
                onClick={startEdit}
                sx={{
                  p: 0.25,
                  color: alpha("#ffffff", 0.6),
                  "&:hover": { color: "#a78bfa" },
                }}
              >
                <EditIcon sx={{ fontSize: 14 }} />
              </IconButton>
            </Tooltip>
            <Tooltip title="Delete">
              <IconButton
                size="small"
                aria-label="Delete conversation"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                }}
                sx={{
                  p: 0.25,
                  color: alpha("#ffffff", 0.6),
                  "&:hover": { color: "#ef4444" },
                }}
              >
                <DeleteIcon sx={{ fontSize: 14 }} />
              </IconButton>
            </Tooltip>
          </Box>
        </>
      )}
    </ListItemButton>
  );
}
