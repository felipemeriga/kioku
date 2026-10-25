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
import MoreVertIcon from "@mui/icons-material/MoreVert";
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
  const spineColor = getSpineColor(ext);
  const statusColor = STATUS_COLORS[doc.status] ?? brand.muted;

  const sourceLabel =
    doc.source_type === "notion"
      ? "Notion"
      : {
          md: "Markdown",
          markdown: "Markdown",
          pdf: "PDF",
          docx: "Word",
          txt: "Text",
          html: "HTML",
        }[ext] ??
        doc.source_type ??
        ext.toUpperCase();
  const updatedAt = doc.last_updated ?? doc.created_at;
  const dateLabel = new Date(updatedAt).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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
        role={variant === "list" ? "row" : undefined}
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
        tabIndex={0}
        onKeyDown={(event) => {
          if (
            event.currentTarget === event.target &&
            (event.key === "Enter" || event.key === " ")
          ) {
            event.preventDefault();
            handleClick();
          }
        }}
        sx={{
          borderRadius: variant === "list" ? 0 : "4px",
          border:
            variant === "list"
              ? "none"
              : `1px solid ${
                  doc.status === "processing"
                    ? alpha(brand.magenta, 0.5)
                    : doc.status === "failed"
                    ? alpha(brand.red, 0.4)
                    : selected
                    ? alpha(brand.magenta, 0.5)
                    : brand.line
                }`,
          borderBottom:
            variant === "list" ? `1px solid ${brand.line}` : undefined,
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
            className="file-row"
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "minmax(0,1fr) 36px",
                md: "minmax(0,1fr) 160px 180px 44px",
              },
              gap: 0,
              px: 2.5,
              py: 2,
              width: "100%",
              alignItems: "center",
              minHeight: 86,
            }}
          >
            <Box
              role="cell"
              className="file-name-cell"
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1.5,
                minWidth: 0,
              }}
            >
              {onSelect && (
                <Checkbox
                  size="small"
                  checked={selected}
                  inputProps={{ "aria-label": `Select ${doc.source_filename}` }}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onSelect(doc.source_filename)}
                  sx={{ p: 0, color: brand.muted }}
                />
              )}
              <Box
                className="file-type"
                aria-hidden="true"
                sx={{
                  border: `1px solid ${brand.lineGlow}`,
                  color: brand.cyan,
                  borderRadius: 1,
                  width: 34,
                  height: 38,
                  flexShrink: 0,
                  display: "grid",
                  placeItems: "center",
                  fontFamily: fonts.mono,
                  fontSize: 11,
                }}
              >
                {doc.source_type === "notion"
                  ? "N"
                  : ext.toUpperCase().slice(0, 4)}
              </Box>
              <Box sx={{ minWidth: 0 }}>
                <Typography
                  className="file-name"
                  sx={{
                    color: brand.text,
                    fontSize: 16,
                    fontWeight: 500,
                    overflowWrap: "anywhere",
                  }}
                >
                  {doc.source_filename}
                </Typography>
                <Typography
                  className="file-chunks"
                  sx={{
                    mt: 0.5,
                    color: doc.status === "failed" ? brand.red : brand.muted,
                    fontSize: 13,
                  }}
                >
                  {doc.chunks} {doc.chunks === 1 ? "chunk" : "chunks"}
                  {doc.status !== "completed" ? ` · ${doc.status}` : ""}
                </Typography>
                <Typography
                  className="file-mobile-metadata"
                  sx={{
                    display: { xs: "block", md: "none" },
                    mt: 0.5,
                    color: brand.muted,
                    fontSize: 13,
                  }}
                >
                  {sourceLabel} · {doc.last_updated ? "" : "Created "}
                  {dateLabel}
                </Typography>
              </Box>
            </Box>
            <Typography
              className="file-source"
              role="cell"
              sx={{
                display: { xs: "none", md: "block" },
                color: brand.muted,
                fontSize: 14,
              }}
            >
              {sourceLabel}
            </Typography>
            <Typography
              role="cell"
              className="file-updated"
              component="time"
              dateTime={updatedAt}
              sx={{
                display: { xs: "none", md: "block" },
                color: brand.muted,
                fontSize: 14,
              }}
            >
              {doc.last_updated ? "" : "Created "}
              {dateLabel}
            </Typography>
            <IconButton
              aria-label={`Options for ${doc.source_filename}`}
              onClick={(e) => {
                e.stopPropagation();
                const rect = e.currentTarget.getBoundingClientRect();
                setContextMenu({ x: rect.right, y: rect.bottom });
              }}
              size="small"
              sx={{ color: brand.muted }}
            >
              <MoreVertIcon fontSize="small" />
            </IconButton>
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
                  fontSize: "0.8125rem",
                  letterSpacing: 0,
                  color: brand.ink,
                  textTransform: "none",
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
                  fontSize: "0.8125rem",
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
                  fontSize: "0.8125rem",
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
