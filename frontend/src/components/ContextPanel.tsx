import { useCallback, useState } from "react";
import {
  Box,
  List,
  ListItemButton,
  ListItemText,
  ListItemIcon,
  IconButton,
  Typography,
  alpha,
} from "@mui/material";
import { useSearchParams } from "react-router-dom";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import FolderTree from "./FolderTree";
import FolderIntegrationsDialog from "./FolderIntegrationsDialog";
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
                  bgcolor: alpha("#7c3aed", 0.15),
                  color: "#a78bfa",
                  "&:hover": { bgcolor: alpha("#7c3aed", 0.25) },
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
            bgcolor: alpha("#7c3aed", 0.15),
            color: "#a78bfa",
            "&:hover": { bgcolor: alpha("#7c3aed", 0.25) },
          }}
        >
          <AddIcon sx={{ fontSize: 14 }} />
        </IconButton>
      </Box>

      <List sx={{ flex: 1, overflow: "auto", px: 0.5 }}>
        {conversations.map((conv) => (
          <ListItemButton
            key={conv.id}
            selected={conv.id === selectedId}
            onClick={() => onSelect(conv.id)}
            sx={{
              borderRadius: 1.5,
              mx: 0.5,
              py: 0.6,
              mb: 0.25,
              "&.Mui-selected": {
                bgcolor: alpha("#7c3aed", 0.12),
                "&:hover": { bgcolor: alpha("#7c3aed", 0.18) },
              },
              "&:hover": {
                bgcolor: alpha("#ffffff", 0.04),
                "& .conv-delete": { opacity: 0.6 },
              },
            }}
          >
            <ListItemIcon sx={{ minWidth: 28 }}>
              <ChatBubbleOutlineIcon
                sx={{ fontSize: 15, color: alpha("#ffffff", 0.3) }}
              />
            </ListItemIcon>
            <ListItemText
              primary={conv.title}
              primaryTypographyProps={{
                noWrap: true,
                variant: "body2",
                sx: {
                  fontWeight: conv.id === selectedId ? 500 : 400,
                },
              }}
            />
            <IconButton
              className="conv-delete"
              size="small"
              sx={{
                opacity: 0,
                transition: "opacity 0.15s",
                p: 0.25,
              }}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(conv.id);
              }}
            >
              <DeleteIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </ListItemButton>
        ))}
      </List>
    </>
  );
}
