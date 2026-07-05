import { useState, useEffect, useCallback } from "react";
import {
  Box,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  IconButton,
  Collapse,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import FolderIcon from "@mui/icons-material/Folder";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DeleteIcon from "@mui/icons-material/Delete";
import HubIcon from "@mui/icons-material/Hub";
import { fetchFolders } from "../lib/api";
import type { Folder } from "../lib/api";
import { brand, fonts } from "../theme";

// Drop-onto-folder support in the tree — mirrors the card-grid drop behavior.
interface FolderDropOps {
  onFileDropped?: (folderId: string | null, filename: string) => void;
  onOsFilesDropped?: (folderId: string | null, files: File[]) => void;
}

interface FolderTreeNodeProps extends FolderDropOps {
  folder: Folder;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  depth: number;
  onRequestDelete: (folderId: string, folderName: string) => void;
  onRequestIntegrations: (
    folderId: string,
    folderName: string,
    kind?: "folder" | "repo"
  ) => void;
}

function FolderTreeNode({
  folder,
  selectedId,
  onSelect,
  depth,
  onRequestDelete,
  onRequestIntegrations,
  onFileDropped,
  onOsFilesDropped,
}: FolderTreeNodeProps) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<Folder[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const isSelected = selectedId === folder.id;

  const loadChildren = useCallback(async () => {
    try {
      const data = await fetchFolders(folder.id);
      setChildren(data);
      setLoaded(true);
    } catch (err) {
      // Tree still opens — the node just shows no children.
      // eslint-disable-next-line no-console
      console.warn(`[FolderTree] failed to load children of ${folder.name}:`, err);
    }
  }, [folder.id, folder.name]);

  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!loaded) await loadChildren();
    setOpen(!open);
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    onRequestDelete(folder.id, folder.name);
  };

  const handleSelect = () => {
    onSelect(folder.id);
    if (!loaded) {
      void loadChildren();
      setOpen(true);
    }
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onRequestIntegrations(folder.id, folder.name, folder.kind);
  };

  return (
    <>
      <ListItemButton
        selected={isSelected}
        onClick={handleSelect}
        onContextMenu={handleContextMenu}
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDragOver(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDragOver(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setDragOver(false);
          const inAppFile = e.dataTransfer.getData("application/x-document-filename");
          if (inAppFile && onFileDropped) {
            onFileDropped(folder.id, inAppFile);
            return;
          }
          const files = Array.from(e.dataTransfer.files);
          if (files.length && onOsFilesDropped) onOsFilesDropped(folder.id, files);
        }}
        sx={{
          pl: 1.25 + depth * 1.75,
          py: 0.4,
          minHeight: 34,
          borderRadius: 1.25,
          mx: 0.5,
          mb: 0.25,
          bgcolor: dragOver ? alpha(brand.violet, 0.18) : undefined,
          border: dragOver ? `1px dashed ${brand.violet2}` : "1px solid transparent",
          "&.Mui-selected": {
            bgcolor: alpha(brand.violet, 0.18),
            "&:hover": { bgcolor: alpha(brand.violet, 0.24) },
          },
          "&:hover": {
            bgcolor: alpha(brand.violet, 0.08),
            "& .folder-actions": { opacity: 1 },
          },
        }}
      >
        <IconButton
          size="small"
          onClick={handleToggle}
          sx={{
            p: 0.25,
            mr: 0.5,
            transition: "transform 0.15s ease",
            transform: open ? "rotate(0deg)" : "rotate(-90deg)",
          }}
        >
          <ExpandMoreIcon sx={{ fontSize: 16, color: brand.muted }} />
        </IconButton>
        <ListItemIcon sx={{ minWidth: 26 }}>
          {folder.kind === "repo" ? (
            // Repos get a distinct icon + cyan tint so at-a-glance it's
            // clear these are the strict-schema, GitHub-bound folders.
            <AccountTreeIcon sx={{ fontSize: 17, color: brand.cyan }} />
          ) : open ? (
            <FolderOpenIcon sx={{ fontSize: 17, color: brand.violet2 }} />
          ) : (
            <FolderIcon sx={{ fontSize: 17, color: brand.violet2 }} />
          )}
        </ListItemIcon>
        <ListItemText
          primary={folder.name}
          primaryTypographyProps={{
            noWrap: true,
            sx: {
              fontFamily: fonts.body,
              fontSize: "0.83rem",
              fontWeight: isSelected ? 600 : 400,
              color: isSelected ? brand.text : brand.muted,
            },
          }}
        />
        <Box
          className="folder-actions"
          sx={{
            display: "flex",
            alignItems: "center",
            opacity: 0,
            transition: "opacity 0.15s",
            gap: 0.25,
          }}
        >
          <Tooltip title="Manage integrations">
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                onRequestIntegrations(folder.id, folder.name, folder.kind);
              }}
              aria-label={`Manage integrations for ${folder.name}`}
              sx={{
                p: 0.25,
                color: brand.muted,
                "&:hover": { color: brand.violet2, bgcolor: alpha(brand.violet, 0.15) },
              }}
            >
              <HubIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete folder">
            <IconButton
              size="small"
              onClick={handleDelete}
              aria-label={`Delete ${folder.name}`}
              sx={{
                p: 0.25,
                color: brand.muted,
                "&:hover": { color: "#ef4444", bgcolor: alpha("#ef4444", 0.15) },
              }}
            >
              <DeleteIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Tooltip>
        </Box>
      </ListItemButton>
      <Collapse in={open} timeout="auto">
        {children.map((child) => (
          <FolderTreeNode
            key={child.id}
            folder={child}
            selectedId={selectedId}
            onSelect={onSelect}
            depth={depth + 1}
            onRequestDelete={onRequestDelete}
            onRequestIntegrations={onRequestIntegrations}
            onFileDropped={onFileDropped}
            onOsFilesDropped={onOsFilesDropped}
          />
        ))}
      </Collapse>
    </>
  );
}

interface FolderTreeProps extends FolderDropOps {
  selectedFolderId: string | null;
  onSelectFolder: (id: string | null) => void;
  onRequestDelete: (folderId: string, folderName: string) => void;
  onRequestIntegrations: (
    folderId: string,
    folderName: string,
    kind?: "folder" | "repo"
  ) => void;
}

export default function FolderTree({
  selectedFolderId,
  onSelectFolder,
  onRequestDelete,
  onRequestIntegrations,
  onFileDropped,
  onOsFilesDropped,
}: FolderTreeProps) {
  const [rootFolders, setRootFolders] = useState<Folder[]>([]);
  const [rootDragOver, setRootDragOver] = useState(false);

  const loadRoot = useCallback(() => {
    // Non-critical: sidebar tree renders empty on failure. Not surfaced as a
    // toast because it fires on every mount + on every `folders-changed`
    // event — a persistent network problem would flood the user. It's
    // logged so devtools still shows the failure.
    fetchFolders(null)
      .then(setRootFolders)
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn("[FolderTree] failed to load root folders:", err);
      });
  }, []);

  useEffect(() => {
    loadRoot();
    const handler = () => loadRoot();
    window.addEventListener("folders-changed", handler);
    return () => window.removeEventListener("folders-changed", handler);
  }, [loadRoot]);

  return (
    <Box sx={{ py: 1 }}>
      <ListItemButton
        selected={selectedFolderId === null}
        onClick={() => onSelectFolder(null)}
        onDragOver={(e) => {
          e.preventDefault();
          setRootDragOver(true);
        }}
        onDragLeave={() => setRootDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setRootDragOver(false);
          const inAppFile = e.dataTransfer.getData("application/x-document-filename");
          if (inAppFile && onFileDropped) {
            onFileDropped(null, inAppFile);
            return;
          }
          const files = Array.from(e.dataTransfer.files);
          if (files.length && onOsFilesDropped) onOsFilesDropped(null, files);
        }}
        sx={{
          py: 0.5,
          minHeight: 36,
          borderRadius: 1.25,
          mx: 0.5,
          mb: 0.25,
          pl: 1.5,
          bgcolor: rootDragOver ? alpha(brand.violet, 0.18) : undefined,
          border: rootDragOver ? `1px dashed ${brand.violet2}` : "1px solid transparent",
          "&.Mui-selected": {
            bgcolor: alpha(brand.violet, 0.18),
            "&:hover": { bgcolor: alpha(brand.violet, 0.24) },
          },
          "&:hover": { bgcolor: alpha(brand.violet, 0.08) },
        }}
      >
        <ListItemIcon sx={{ minWidth: 26 }}>
          <FolderIcon sx={{ fontSize: 17, color: brand.muted }} />
        </ListItemIcon>
        <ListItemText
          primary="All Documents"
          primaryTypographyProps={{
            sx: {
              fontFamily: fonts.body,
              fontSize: "0.83rem",
              fontWeight: selectedFolderId === null ? 600 : 400,
              color: selectedFolderId === null ? brand.text : brand.muted,
            },
          }}
        />
      </ListItemButton>

      {rootFolders.length > 0 && (
        <Typography
          variant="overline"
          sx={{
            fontFamily: fonts.mono,
            px: 2,
            pt: 1.5,
            pb: 0.5,
            display: "block",
            color: brand.muted,
            letterSpacing: "0.24em",
            fontSize: "0.6rem",
          }}
        >
          FOLDERS
        </Typography>
      )}

      <List disablePadding dense>
        {rootFolders.map((folder) => (
          <FolderTreeNode
            key={folder.id}
            folder={folder}
            selectedId={selectedFolderId}
            onSelect={onSelectFolder}
            depth={0}
            onRequestDelete={onRequestDelete}
            onRequestIntegrations={onRequestIntegrations}
            onFileDropped={onFileDropped}
            onOsFilesDropped={onOsFilesDropped}
          />
        ))}
      </List>
    </Box>
  );
}
