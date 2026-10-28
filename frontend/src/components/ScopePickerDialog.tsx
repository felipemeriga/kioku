import { brand } from "../theme";
/**
 * ScopePickerDialog — choose a RAG scope: any folder (searches its whole
 * subtree) or a single document inside the current folder view.
 *
 * Navigation mirrors MoveDialog; on top of folders it also lists the files
 * of the current level so a single document can be picked as the scope.
 */
import { useCallback, useState } from "react";
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
  CircularProgress,
  alpha,
} from "@mui/material";
import FolderIcon from "@mui/icons-material/Folder";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CenterFocusStrongIcon from "@mui/icons-material/CenterFocusStrong";
import DescriptionIcon from "@mui/icons-material/Description";
import { useQuery } from "@tanstack/react-query";
import { fetchDocuments, fetchFolders } from "../lib/api";
import { qk } from "../lib/queryKeys";
import type { ChatScope, Folder } from "../lib/api";
import { messageFromError } from "./ToastProvider";

export default function ScopePickerDialog({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (scope: ChatScope) => void;
}) {
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [currentName, setCurrentName] = useState<string>("All documents");
  const [stack, setStack] = useState<{ id: string | null; name: string }[]>([]);

  // Both share their caches with the Documents grid (same query keys).
  const foldersQuery = useQuery({
    queryKey: qk.folders(currentId),
    queryFn: () => fetchFolders(currentId),
    enabled: open,
  });
  const docsQuery = useQuery({
    queryKey: qk.documents(currentId),
    queryFn: () => fetchDocuments(currentId ?? undefined),
    enabled: open,
  });
  const folders = foldersQuery.data ?? [];
  const docs = docsQuery.data ?? [];
  const loadError =
    foldersQuery.isError || docsQuery.isError
      ? messageFromError(foldersQuery.error ?? docsQuery.error)
      : null;
  const loading = foldersQuery.isPending || docsQuery.isPending;

  const handleOpen = useCallback(() => {
    setCurrentId(null);
    setCurrentName("All documents");
    setStack([]);
  }, []);

  const navigateInto = (folder: Folder) => {
    setStack((prev) => [...prev, { id: currentId, name: currentName }]);
    setCurrentId(folder.id);
    setCurrentName(folder.name);
  };

  const navigateBack = () => {
    const prev = stack[stack.length - 1];
    setStack((s) => s.slice(0, -1));
    setCurrentId(prev?.id ?? null);
    setCurrentName(prev?.name ?? "All documents");
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
      <DialogTitle>Scope the search</DialogTitle>
      <DialogContent sx={{ px: 3, pb: 3 }}>
        <Box
          sx={{ display: "flex", alignItems: "center", gap: 1, px: 1, mb: 1 }}
        >
          {stack.length > 0 && (
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
          <Typography
            variant="body2"
            sx={{ color: alpha("#ffffff", 0.5) }}
            noWrap
          >
            {currentName}
          </Typography>
        </Box>

        <List
          dense
          sx={{
            maxHeight: 340,
            overflow: "auto",
            border: `1px solid ${brand.line}`,
            borderRadius: "5px",
            p: 1.5,
            "& .MuiListItemButton-root": { p: "11px 12px", m: 0 },
            "& .MuiListItemText-primary": { fontSize: 14 },
          }}
        >
          {currentId !== null && (
            <ListItemButton
              onClick={() =>
                onSelect({ folderId: currentId, folderName: currentName })
              }
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
                <CenterFocusStrongIcon sx={{ color: brand.magenta }} />
              </ListItemIcon>
              <ListItemText
                primary={`Search only “${currentName}”`}
                primaryTypographyProps={{ fontWeight: 500, color: brand.cyan }}
              />
            </ListItemButton>
          )}

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

          {docs.map((d) => (
            <ListItemButton
              key={d.source_filename}
              onClick={() =>
                onSelect({
                  folderId: currentId,
                  folderName: currentName,
                  filename: d.source_filename,
                })
              }
              sx={{ borderRadius: 2, mx: 0.5, mb: 0.25 }}
            >
              <ListItemIcon>
                <DescriptionIcon sx={{ color: alpha("#ffffff", 0.5) }} />
              </ListItemIcon>
              <ListItemText
                primary={d.source_filename}
                primaryTypographyProps={{ noWrap: true }}
              />
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

          {loading && (
            <Box
              role="status"
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 1,
                py: 2,
                color: brand.muted,
              }}
            >
              <CircularProgress size={18} color="inherit" /> Loading folders and
              files…
            </Box>
          )}
          {!loading &&
            !loadError &&
            folders.length === 0 &&
            docs.length === 0 && (
              <Typography
                variant="body2"
                sx={{
                  color: alpha("#ffffff", 0.3),
                  textAlign: "center",
                  py: 2,
                }}
              >
                Empty folder
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
