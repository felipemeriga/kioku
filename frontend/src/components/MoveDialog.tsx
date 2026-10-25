import { brand } from "../theme";
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
import { useQuery } from "@tanstack/react-query";
import { fetchFolders } from "../lib/api";
import type { Folder } from "../lib/api";
import { qk } from "../lib/queryKeys";
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
  const [currentParentId, setCurrentParentId] = useState<string | null>(null);
  const [parentStack, setParentStack] = useState<(string | null)[]>([]);

  // Shares the ['folders', parentId] cache with the Documents grid.
  const foldersQuery = useQuery({
    queryKey: qk.folders(currentParentId),
    queryFn: () => fetchFolders(currentParentId),
    enabled: open,
  });
  const folders = foldersQuery.data ?? [];
  const loadError = foldersQuery.isError
    ? messageFromError(foldersQuery.error)
    : null;

  const handleOpen = useCallback(() => {
    setCurrentParentId(null);
    setParentStack([]);
  }, []);

  const navigateInto = (folder: Folder) => {
    setParentStack((prev) => [...prev, currentParentId]);
    setCurrentParentId(folder.id);
  };

  const navigateBack = () => {
    const prev = parentStack[parentStack.length - 1];
    setParentStack((s) => s.slice(0, -1));
    setCurrentParentId(prev ?? null);
  };

  const handleMoveHere = () => {
    onSelect(currentParentId);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      PaperProps={{ sx: { maxWidth: 520, borderRadius: "8px" } }}
      fullWidth
      TransitionProps={{ onEnter: handleOpen }}
    >
      <DialogTitle>{title}</DialogTitle>
      <DialogContent sx={{ px: 3, pb: 3 }}>
        <Box
          sx={{ display: "flex", alignItems: "center", gap: 1, px: 1, mb: 1 }}
        >
          {parentStack.length > 0 && (
            <Button
              size="small"
              startIcon={<ArrowBackIcon sx={{ fontSize: 16 }} />}
              onClick={navigateBack}
              sx={{
                minWidth: 0,
                textTransform: "none",
                color: alpha("#ffffff", 0.6),
              }}
            >
              Back
            </Button>
          )}
          <Typography variant="body2" sx={{ color: alpha("#ffffff", 0.5) }}>
            {currentParentId === null ? "Root" : "Subfolder"}
          </Typography>
        </Box>

        <List
          dense
          sx={{
            maxHeight: 300,
            overflow: "auto",
            border: `1px solid ${brand.line}`,
            borderRadius: "5px",
            p: 1.5,
            "& .MuiListItemButton-root": { p: "11px 12px", m: 0 },
            "& .MuiListItemText-primary": { fontSize: 14 },
          }}
        >
          <ListItemButton
            onClick={handleMoveHere}
            sx={{
              borderRadius: 2,
              mx: 0.5,
              mb: 0.5,
              border: 1,
              borderStyle: "dashed",
              borderColor: alpha(brand.magenta, 0.3),
              "&:hover": { bgcolor: alpha(brand.magenta, 0.08) },
            }}
          >
            <ListItemIcon>
              <DriveFileMoveIcon sx={{ color: brand.magenta }} />
            </ListItemIcon>
            <ListItemText
              primary={currentParentId === null ? "Move to root" : "Move here"}
              primaryTypographyProps={{ fontWeight: 500, color: brand.cyan }}
            />
          </ListItemButton>

          {folders.map((f) => (
            <ListItemButton
              key={f.id}
              onClick={() => navigateInto(f)}
              sx={{ borderRadius: 2, mx: 0.5, mb: 0.25 }}
            >
              <ListItemIcon>
                <FolderIcon sx={{ color: brand.magenta }} />
              </ListItemIcon>
              <ListItemText primary={f.name} />
            </ListItemButton>
          ))}

          {loadError && (
            <Typography
              variant="body2"
              sx={{ color: brand.red, textAlign: "center", py: 2, px: 2 }}
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
