import { useState, useCallback } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Box,
  Typography,
  alpha,
} from "@mui/material";
import FolderIcon from "@mui/icons-material/Folder";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DriveFileMoveIcon from "@mui/icons-material/DriveFileMove";
import { fetchFolders } from "../lib/api";
import type { Folder } from "../lib/api";
import { messageFromError } from "./ToastProvider";

interface MoveDialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  onSelect: (folderId: string | null) => void;
}

export default function MoveDialog({
  open,
  title,
  onClose,
  onSelect,
}: MoveDialogProps) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [currentParentId, setCurrentParentId] = useState<string | null>(null);
  const [parentStack, setParentStack] = useState<(string | null)[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadFolders = useCallback((parentId: string | null) => {
    setLoadError(null);
    fetchFolders(parentId)
      .then(setFolders)
      .catch((err) => {
        setFolders([]);
        setLoadError(messageFromError(err));
      });
  }, []);

  const handleOpen = useCallback(() => {
    setCurrentParentId(null);
    setParentStack([]);
    loadFolders(null);
  }, [loadFolders]);

  const navigateInto = (folder: Folder) => {
    setParentStack((prev) => [...prev, currentParentId]);
    setCurrentParentId(folder.id);
    loadFolders(folder.id);
  };

  const navigateBack = () => {
    const prev = parentStack[parentStack.length - 1];
    setParentStack((s) => s.slice(0, -1));
    setCurrentParentId(prev ?? null);
    loadFolders(prev ?? null);
  };

  const handleMoveHere = () => {
    onSelect(currentParentId);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xs"
      fullWidth
      TransitionProps={{ onEnter: handleOpen }}
    >
      <DialogTitle>{title}</DialogTitle>
      <DialogContent sx={{ px: 1, pb: 0 }}>
        <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 1, mb: 1 }}>
          {parentStack.length > 0 && (
            <Button
              size="small"
              startIcon={<ArrowBackIcon sx={{ fontSize: 16 }} />}
              onClick={navigateBack}
              sx={{ minWidth: 0, textTransform: "none", color: alpha("#ffffff", 0.6) }}
            >
              Back
            </Button>
          )}
          <Typography variant="body2" sx={{ color: alpha("#ffffff", 0.5) }}>
            {currentParentId === null ? "Root" : "Subfolder"}
          </Typography>
        </Box>

        <List dense sx={{ maxHeight: 300, overflow: "auto" }}>
          <ListItemButton
            onClick={handleMoveHere}
            sx={{
              borderRadius: 2,
              mx: 0.5,
              mb: 0.5,
              border: 1,
              borderStyle: "dashed",
              borderColor: alpha("#7c3aed", 0.3),
              "&:hover": { bgcolor: alpha("#7c3aed", 0.08) },
            }}
          >
            <ListItemIcon>
              <DriveFileMoveIcon sx={{ color: "#7c3aed" }} />
            </ListItemIcon>
            <ListItemText
              primary={currentParentId === null ? "Move to root" : "Move here"}
              primaryTypographyProps={{ fontWeight: 500, color: "#a78bfa" }}
            />
          </ListItemButton>

          {folders.map((f) => (
            <ListItemButton
              key={f.id}
              onClick={() => navigateInto(f)}
              sx={{ borderRadius: 2, mx: 0.5, mb: 0.25 }}
            >
              <ListItemIcon>
                <FolderIcon sx={{ color: "#7c3aed" }} />
              </ListItemIcon>
              <ListItemText primary={f.name} />
            </ListItemButton>
          ))}

          {loadError && (
            <Typography
              variant="body2"
              sx={{ color: "#ef4444", textAlign: "center", py: 2, px: 2 }}
            >
              Couldn't load folders: {loadError}
            </Typography>
          )}

          {!loadError && folders.length === 0 && (
            <Typography
              variant="body2"
              sx={{ color: alpha("#ffffff", 0.3), textAlign: "center", py: 2 }}
            >
              No subfolders
            </Typography>
          )}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
      </DialogActions>
    </Dialog>
  );
}
