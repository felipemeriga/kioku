import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Alert,
  Button,
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
import { brand } from "../theme";
import { hudLabel } from "./neo/sx";

interface ContextPanelProps {
  activePage: AppPage;
  open: boolean;
  conversations: Conversation[];
  conversationsLoading?: boolean;
  conversationsError?: string | null;
  onRetryConversations?: () => void;
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
  conversationsLoading = false,
  conversationsError = null,
  onRetryConversations,
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
      if (id === selectedFolderId) return;
      setSearchParams(id ? { folder: id } : {});
    },
    [selectedFolderId, setSearchParams]
  );

  const handleDeleteFolder = useCallback(
    (folderId: string, folderName: string) => {
      onRequestDeleteFolder?.(folderId, folderName);
    },
    [onRequestDeleteFolder]
  );

  const [integrationsTarget, setIntegrationsTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const handleRequestIntegrations = useCallback(
    (folderId: string, folderName: string) => {
      setIntegrationsTarget({ id: folderId, name: folderName });
    },
    []
  );

  if (!open) return null;

  return (
    <Box
      component="aside"
      aria-label={
        activePage === "/documents" ? "Folder navigator" : "Conversations"
      }
      data-testid="context-panel"
      sx={{
        width: 248,
        maxWidth: "100%",
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        bgcolor: brand.surface2,

        borderRight: `1px solid ${brand.line}`,
        flexShrink: 0,
      }}
    >
      {activePage === "/" && (
        <ChatPanel
          conversations={conversations}
          loading={conversationsLoading}
          error={conversationsError}
          onRetry={onRetryConversations}
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
              px: "14px",
              pt: 2,
              pb: 1.25,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <Typography sx={hudLabel}>Folders</Typography>
            {onNewFolder && (
              <IconButton
                size="small"
                aria-label="New folder"
                onClick={onNewFolder}
                sx={{
                  width: 28,
                  height: 28,
                  borderRadius: "3px",
                  border: `1px solid ${brand.magenta}55`,
                  bgcolor: `${brand.magenta}14`,
                  color: brand.magenta,
                  "&:hover": { bgcolor: `${brand.magenta}25` },
                }}
              >
                <AddIcon sx={{ fontSize: 16 }} />
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
  loading,
  error,
  onRetry,
  selectedId,
  onSelect,
  onNew,
  onDelete,
}: {
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
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
          px: 2,
          pt: 2.5,
          pb: 2,
          display: "flex",
          flexDirection: "column",
          gap: 1.5,
        }}
      >
        <Typography sx={{ fontSize: 14, color: brand.muted }}>
          Conversations
        </Typography>
        <Button
          data-testid="new-chat-button"
          aria-label="New conversation"
          variant="outlined"
          startIcon={<AddIcon sx={{ fontSize: 16 }} />}
          onClick={onNew}
          fullWidth
        >
          New conversation
        </Button>
      </Box>

      {loading && (
        <Typography role="status" sx={{ px: 2, py: 1, color: brand.muted }}>
          Loading conversations…
        </Typography>
      )}
      {error && (
        <Alert severity="error" sx={{ mx: 1, mb: 1 }}>
          Couldn’t load conversations. {error}
          <Button size="small" onClick={onRetry}>
            Retry
          </Button>
        </Alert>
      )}
      {!loading && !error && conversations.length === 0 && (
        <Typography sx={{ px: 2, py: 1, color: brand.muted }}>
          No conversations yet.
        </Typography>
      )}
      <List sx={{ flex: 1, overflow: "auto", px: "8px" }}>
        {conversations.map((conv, index) => {
          const group = conversationGroup(conv.updated_at);
          return (
            <Fragment key={conv.id}>
              {(index === 0 ||
                group !==
                  conversationGroup(conversations[index - 1].updated_at)) && (
                <Typography
                  component="li"
                  sx={{
                    listStyle: "none",
                    fontSize: 12,
                    color: brand.muted,
                    px: 1.5,
                    pt: 1.5,
                    pb: 0.75,
                  }}
                >
                  {group}
                </Typography>
              )}
              <ConversationRow
                conv={conv}
                isSelected={conv.id === selectedId}
                onSelect={() => onSelect(conv.id)}
                onDelete={() => onDelete(conv.id)}
              />
            </Fragment>
          );
        })}
      </List>
    </>
  );
}

function conversationGroup(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Earlier";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, { month: "long", year: "numeric" });
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
      component="li"
      data-testid="conversation-row"
      aria-label={`Open conversation: ${conv.title}`}
      aria-current={isSelected ? "true" : undefined}
      selected={isSelected}
      onClick={editing ? undefined : onSelect}
      onDoubleClick={(e) => startEdit(e)}
      sx={{
        borderRadius: "3px",
        px: "12px",
        py: "10px",
        mb: "2px",
        height: "auto",
        ...(isSelected
          ? {
              background: `${brand.magenta}22`,
              boxShadow: `inset 2px 0 0 ${brand.magenta}`,
              color: brand.text,
              fontWeight: 500,
              "&:hover": { background: `${brand.magenta}33` },
              "& .conv-actions": { opacity: 1 },
            }
          : {
              color: brand.text,
              "&:hover": {
                background: alpha("#ffffff", 0.04),
                "& .conv-actions": { opacity: 1 },
              },
            }),
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
            fontSize: 13,
            color: "#fff",
            "& input": {
              padding: 0,
              border: `1px solid ${alpha(brand.magenta, 0.4)}`,
              borderRadius: "3px",
              px: 1,
              py: 0.4,
              bgcolor: alpha(brand.magenta, 0.08),
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
              sx: {
                fontWeight: isSelected ? 500 : 400,
                fontSize: "13px",
                color: isSelected ? brand.text : brand.muted,
              },
            }}
          />
          <Box
            className="conv-actions"
            sx={{
              display: "flex",
              alignItems: "center",
              opacity: 1,
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
                  "&:hover": { color: brand.purple },
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
                  "&:hover": { color: brand.red },
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
