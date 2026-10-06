import { useState, useCallback } from "react";
import {
  Box,
  Typography,
  IconButton,
  Menu,
  MenuItem,
  ListItemIcon,
  ListItemText,
  Checkbox,
  Snackbar,
  alpha,
} from "@mui/material";
import PictureAsPdfIcon from "@mui/icons-material/PictureAsPdf";
import DescriptionIcon from "@mui/icons-material/Description";
import CodeIcon from "@mui/icons-material/Code";
import TextSnippetIcon from "@mui/icons-material/TextSnippet";
import ArticleIcon from "@mui/icons-material/Article";
import DownloadIcon from "@mui/icons-material/Download";
import DeleteIcon from "@mui/icons-material/Delete";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DriveFileMoveIcon from "@mui/icons-material/DriveFileMove";
import VisibilityIcon from "@mui/icons-material/Visibility";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import type { DocumentInfo } from "../lib/api";
import MoveDialog from "./MoveDialog";
import { brand, fonts } from "../theme";

interface DocumentCardProps {
  doc: DocumentInfo;
  selected?: boolean;
  onSelect?: (filename: string) => void;
  onDelete: (filename: string) => void;
  onDownload: (filename: string) => void;
  onMove?: (filename: string, folderId: string | null) => void;
  /** When set, clicking the card opens the document (selection stays on the
   *  checkbox); without it, clicking falls back to toggling selection. */
  onOpen?: (filename: string) => void;
  /** Opens a chat scoped to just this document. */
  onChat?: (filename: string) => void;
  /** "grid" (default) renders the tile; "list" renders a compact single row. */
  variant?: "grid" | "list";
}

const FILE_ICONS: Record<string, { icon: React.ReactNode; color: string }> = {
  pdf: { icon: <PictureAsPdfIcon />, color: "#ef4444" },
  docx: { icon: <DescriptionIcon />, color: "#3b82f6" },
  md: { icon: <ArticleIcon />, color: "#10b981" },
  html: { icon: <CodeIcon />, color: "#f59e0b" },
  txt: { icon: <TextSnippetIcon />, color: alpha("#ffffff", 0.5) },
};

// Spine color by extension — matches mockup
const SPINE_COLORS: Record<string, string> = {
  md: "#10b981",
  pdf: "#ef4444",
  docx: "#3b82f6",
  txt: brand.muted,
  html: brand.amber,
  py: brand.purple,
};

function getSpineColor(ext: string): string {
  return SPINE_COLORS[ext] ?? brand.muted;
}

// Status chip colors — border + text from mockup
const STATUS_COLORS: Record<string, string> = {
  completed: brand.green,
  processing: brand.magenta,
  failed: brand.red,
};

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function DocumentCard({
  doc,
  selected,
  onSelect,
  onDelete,
  onDownload,
  onMove,
  onOpen,
  onChat,
  variant = "grid",
}: DocumentCardProps) {
  const ext = doc.source_filename.split(".").pop()?.toLowerCase() || "txt";
  const fileStyle = FILE_ICONS[ext] || FILE_ICONS.txt;
  const spineColor = getSpineColor(ext);
  const statusColor = STATUS_COLORS[doc.status] ?? brand.muted;

  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [moveOpen, setMoveOpen] = useState(false);
  const [snackOpen, setSnackOpen] = useState(false);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY });
  }, []);

  const closeMenu = () => setContextMenu(null);

  const handleCopy = () => {
    navigator.clipboard.writeText(doc.source_filename);
    setSnackOpen(true);
    closeMenu();
  };

  const handleDownload = () => {
    onDownload(doc.source_filename);
    closeMenu();
  };

  const handleDelete = () => {
    onDelete(doc.source_filename);
    closeMenu();
  };

  const handleMoveOpen = () => {
    closeMenu();
    setMoveOpen(true);
  };

  const handleMoveSelect = (folderId: string | null) => {
    onMove?.(doc.source_filename, folderId);
    setMoveOpen(false);
  };

  const handleClick = () => {
    if (onOpen) {
      onOpen(doc.source_filename);
    } else {
      onSelect?.(doc.source_filename);
    }
  };

  const handleOpenFromMenu = () => {
    closeMenu();
    onOpen?.(doc.source_filename);
  };

  // Notion-synced docs mirror the Notion page tree — moving them locally
  // would be undone (or fought) by the next sync, so they can't be dragged.
  const movable = doc.source_type !== "notion";

  return (
    <>
      <Box
        draggable={movable}
        onDragStart={
          movable
            ? (e: React.DragEvent) => {
                e.dataTransfer.setData(
                  "application/x-document-filename",
                  doc.source_filename
                );
                e.dataTransfer.effectAllowed = "move";
              }
            : undefined
        }
        onContextMenu={handleContextMenu}
        onClick={handleClick}
        sx={{
          borderRadius: "4px",
          border: `1px solid ${
            doc.status === "processing"
              ? alpha(brand.magenta, 0.5)
              : doc.status === "failed"
              ? alpha(brand.red, 0.4)
              : selected
              ? alpha(brand.magenta, 0.5)
              : brand.line
          }`,
          bgcolor: brand.surface,
          overflow: "hidden",
          transition: "all 0.2s ease",
          position: "relative",
          cursor: onOpen ? "pointer" : "context-menu",
          ...(variant === "grid"
            ? {
                display: "flex",
                height: 112,
              }
            : {
                display: "flex",
                alignItems: "center",
              }),
          ...(selected && {
            bgcolor: alpha(brand.magenta, 0.06),
            boxShadow: `0 0 0 1px ${alpha(brand.magenta, 0.3)}`,
          }),
          "&:hover": {
            borderColor: selected ? alpha(brand.magenta, 0.5) : brand.lineGlow,
            "& .doc-actions": { opacity: 1 },
            "& .doc-checkbox": { opacity: 1 },
          },
        }}
      >
        {variant === "list" ? (
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1.25,
              px: 1.5,
              py: 0.75,
              width: "100%",
            }}
          >
            {onSelect && (
              <Checkbox
                className="doc-checkbox"
                checked={selected}
                size="small"
                onClick={(e) => e.stopPropagation()}
                onChange={() => onSelect(doc.source_filename)}
                sx={{
                  opacity: selected ? 1 : 0,
                  transition: "opacity 0.15s",
                  p: 0,
                  color: alpha(brand.magenta, 0.5),
                  "&.Mui-checked": { color: brand.magenta },
                }}
              />
            )}
            {/* Colored type indicator for list mode */}
            <Box
              sx={{
                width: 4,
                alignSelf: "stretch",
                borderRadius: "2px",
                bgcolor: spineColor,
                flexShrink: 0,
              }}
            />
            <Box
              sx={{
                width: 26,
                height: 26,
                borderRadius: 1.5,
                bgcolor: alpha(fileStyle.color, 0.1),
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: fileStyle.color,
                flexShrink: 0,
                "& .MuiSvgIcon-root": { fontSize: 15 },
              }}
            >
              {fileStyle.icon}
            </Box>
            <Typography
              variant="body2"
              noWrap
              sx={{ fontWeight: 500, flex: 1, minWidth: 0 }}
            >
              {doc.source_filename}
            </Typography>
            <Typography
              variant="caption"
              noWrap
              sx={{
                color: brand.muted,
                flexShrink: 0,
                fontFamily: fonts.mono,
                fontSize: "0.68rem",
              }}
            >
              {doc.chunks} chunks · {timeAgo(doc.created_at)}
            </Typography>
            <Box
              sx={{
                display: "inline-flex",
                alignItems: "center",
                gap: "4px",
                px: "7px",
                py: "1px",
                border: `1px solid ${statusColor}`,
                borderRadius: "3px",
                color: statusColor,
                fontFamily: fonts.mono,
                fontSize: "0.65rem",
                fontWeight: 500,
                flexShrink: 0,
                ...(doc.status === "processing" && {
                  animation: "pulse 1.5s infinite",
                  "@keyframes pulse": {
                    "0%, 100%": { opacity: 1 },
                    "50%": { opacity: 0.5 },
                  },
                }),
              }}
            >
              <span aria-hidden>●</span>
              <span>{doc.status}</span>
            </Box>
            <Box
              className="doc-actions"
              sx={{
                display: "flex",
                gap: 0.25,
                opacity: 0,
                transition: "opacity 0.15s",
                flexShrink: 0,
              }}
            >
              {doc.has_file && (
                <IconButton
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDownload(doc.source_filename);
                  }}
                  sx={{ p: 0.5 }}
                >
                  <DownloadIcon sx={{ fontSize: 15 }} />
                </IconButton>
              )}
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(doc.source_filename);
                }}
                sx={{ p: 0.5 }}
              >
                <DeleteIcon sx={{ fontSize: 15 }} />
              </IconButton>
            </Box>
          </Box>
        ) : (
          <>
            {/* Colored left spine with vertical ext text */}
            <Box
              sx={{
                width: 30,
                flexShrink: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                bgcolor: spineColor,
                alignSelf: "stretch",
              }}
            >
              <Typography
                sx={{
                  writingMode: "vertical-rl",
                  transform: "rotate(180deg)",
                  fontFamily: fonts.mono,
                  fontWeight: 600,
                  fontSize: "0.62rem",
                  letterSpacing: "0.2em",
                  color: brand.ink,
                  textTransform: "uppercase",
                  userSelect: "none",
                }}
              >
                {ext.toUpperCase()}
              </Typography>
            </Box>

            {/* Card body */}
            <Box
              sx={{
                flex: 1,
                minWidth: 0,
                px: "14px",
                py: "12px",
                display: "flex",
                flexDirection: "column",
                gap: "8px",
              }}
            >
              {onSelect && (
                <Checkbox
                  className="doc-checkbox"
                  checked={selected}
                  size="small"
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onSelect(doc.source_filename)}
                  sx={{
                    position: "absolute",
                    top: 6,
                    left: 38,
                    opacity: selected ? 1 : 0,
                    transition: "opacity 0.15s",
                    p: 0,
                    color: alpha(brand.magenta, 0.5),
                    "&.Mui-checked": { color: brand.magenta },
                  }}
                />
              )}
              <Typography
                variant="body2"
                noWrap
                sx={{ fontWeight: 500, fontSize: "0.875rem" }}
              >
                {doc.source_filename}
              </Typography>
              <Box
                sx={{
                  alignSelf: "flex-start",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                  px: "7px",
                  py: "2px",
                  border: `1px solid ${statusColor}`,
                  borderRadius: "3px",
                  color: statusColor,
                  fontFamily: fonts.mono,
                  fontSize: "0.68rem",
                  fontWeight: 500,
                  ...(doc.status === "processing" && {
                    animation: "pulse 1.5s infinite",
                    "@keyframes pulse": {
                      "0%, 100%": { opacity: 1 },
                      "50%": { opacity: 0.5 },
                    },
                  }),
                }}
              >
                <span aria-hidden>●</span>
                <span>{doc.status}</span>
              </Box>
              <Typography
                sx={{
                  fontFamily: fonts.mono,
                  fontSize: "0.68rem",
                  color: brand.muted,
                }}
              >
                {doc.chunks} chunks · {timeAgo(doc.created_at)}
              </Typography>
            </Box>

            {/* Hover action buttons */}
            <Box
              className="doc-actions"
              sx={{
                position: "absolute",
                top: 6,
                right: 6,
                display: "flex",
                gap: 0.25,
                opacity: 0,
                transition: "opacity 0.15s",
              }}
            >
              {doc.has_file && (
                <IconButton
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDownload(doc.source_filename);
                  }}
                  sx={{ p: 0.5 }}
                >
                  <DownloadIcon sx={{ fontSize: 16 }} />
                </IconButton>
              )}
              <IconButton
                size="small"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(doc.source_filename);
                }}
                sx={{ p: 0.5 }}
              >
                <DeleteIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Box>
          </>
        )}
      </Box>

      {/* Right-click context menu */}
      <Menu
        open={contextMenu !== null}
        onClose={closeMenu}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu ? { top: contextMenu.y, left: contextMenu.x } : undefined
        }
      >
        {onOpen && (
          <MenuItem onClick={handleOpenFromMenu}>
            <ListItemIcon>
              <VisibilityIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Open</ListItemText>
          </MenuItem>
        )}
        {onChat && (
          <MenuItem
            onClick={() => {
              closeMenu();
              onChat(doc.source_filename);
            }}
          >
            <ListItemIcon>
              <ChatBubbleOutlineIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Chat with this file</ListItemText>
          </MenuItem>
        )}
        <MenuItem onClick={handleCopy}>
          <ListItemIcon>
            <ContentCopyIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>Copy filename</ListItemText>
        </MenuItem>
        {doc.has_file && (
          <MenuItem onClick={handleDownload}>
            <ListItemIcon>
              <DownloadIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Download</ListItemText>
          </MenuItem>
        )}
        {onMove && movable && (
          <MenuItem onClick={handleMoveOpen}>
            <ListItemIcon>
              <DriveFileMoveIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText>Move to folder</ListItemText>
          </MenuItem>
        )}
        <MenuItem onClick={handleDelete} sx={{ color: "#ef4444" }}>
          <ListItemIcon>
            <DeleteIcon fontSize="small" sx={{ color: "#ef4444" }} />
          </ListItemIcon>
          <ListItemText>Delete</ListItemText>
        </MenuItem>
      </Menu>

      {/* Move dialog */}
      <MoveDialog
        open={moveOpen}
        title={`Move "${doc.source_filename}"`}
        onClose={() => setMoveOpen(false)}
        onSelect={handleMoveSelect}
      />

      {/* Copy feedback */}
      <Snackbar
        open={snackOpen}
        autoHideDuration={2000}
        onClose={() => setSnackOpen(false)}
        message="Filename copied to clipboard"
      />
    </>
  );
}
