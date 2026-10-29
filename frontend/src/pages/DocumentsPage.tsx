import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import {
  Box,
  Typography,
  Button,
  IconButton,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  TextField,
  alpha,
  Paper,
  Badge,
  Tooltip,
  InputAdornment,
  Stack,
  Chip,
  ToggleButton,
  ToggleButtonGroup,
  Tabs,
  Tab,
  Skeleton,
} from "@mui/material";
import { useNavigate, useSearchParams } from "react-router-dom";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import DeleteIcon from "@mui/icons-material/Delete";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import FolderIcon from "@mui/icons-material/Folder";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import DriveFileMoveIcon from "@mui/icons-material/DriveFileMove";
import CloseIcon from "@mui/icons-material/Close";
import SearchIcon from "@mui/icons-material/Search";
import GridViewIcon from "@mui/icons-material/GridView";
import ViewListIcon from "@mui/icons-material/ViewList";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolder";
import HomeIcon from "@mui/icons-material/Home";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { useDocuments } from "../hooks/useDocuments";
import { useIngestionStatus } from "../hooks/useIngestionStatus";
import { createFolder, deleteFolder, downloadDocument } from "../lib/api";
import type { Breadcrumb } from "../lib/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  breadcrumbOptions,
  folderOptions,
  prefetchFolder,
} from "../lib/folderQueries";
import DocumentCard from "../components/DocumentCard";
import DocumentViewerDrawer from "../components/DocumentViewerDrawer";
import MoveDialog from "../components/MoveDialog";
import IngestionDrawer from "../components/IngestionDrawer";
import BriefingPanel from "../components/BriefingPanel";
import DocumentationPanel from "../components/DocumentationPanel";
import StatusPanel from "../components/StatusPanel";
import LearningsPanel from "../components/LearningsPanel";
import FolderIntegrationsDialog from "../components/FolderIntegrationsDialog";
import NotionFolderIndicator from "../components/NotionFolderIndicator";
import { useToast, messageFromError } from "../components/ToastProvider";
import { brand, fonts } from "../theme";
import CornerCard from "../components/neo/CornerCard";

const ACCEPTED_TYPES =
  ".txt,.text,.md,.markdown,.pdf,.docx,.html,.htm,.json,.yaml,.yml,.png,.jpg,.jpeg,.mp3,.webm,.m4a";

export default function DocumentsPage() {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [, setDragOver] = useState(false);
  const [integrationsTarget, setIntegrationsTarget] = useState<{
    id: string;
    name: string;
    kind?: "folder" | "repo";
  } | null>(null);
  const [globalDropActive, setGlobalDropActive] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // Persisted so the choice survives navigation and reloads — without this
  // the toggle silently reset to grid on every visit.
  const [viewMode, setViewMode] = useState<"grid" | "list">(() =>
    localStorage.getItem("kioku.documents.viewMode") === "grid"
      ? "grid"
      : "list",
  );
  useEffect(() => {
    localStorage.setItem("kioku.documents.viewMode", viewMode);
  }, [viewMode]);
  const queryClient = useQueryClient();
  const [folderTab, setFolderTab] = useState<
    "files" | "briefing" | "status" | "learnings"
  >("files");
  const [viewerFile, setViewerFile] = useState<string | null>(null);

  // Folder navigation via URL search params (shared with ContextPanel)
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const currentFolderId = searchParams.get("folder") || null;
  const setCurrentFolderId = useCallback(
    (id: string | null) => {
      if (id === currentFolderId) return;
      setSearchParams(id ? { folder: id } : {});
    },
    [currentFolderId, setSearchParams],
  );
  const [newFolderOpen, setNewFolderOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");

  // Multi-select
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [bulkMoveOpen, setBulkMoveOpen] = useState(false);

  const toggleFileSelect = useCallback((filename: string) => {
    setSelectedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(filename)) next.delete(filename);
      else next.add(filename);
      return next;
    });
  }, []);

  const clearSelection = () => setSelectedFiles(new Set());

  const handleBulkMove = (folderId: string | null) => {
    for (const filename of selectedFiles) {
      move(filename, folderId);
    }
    clearSelection();
    setBulkMoveOpen(false);
  };

  const handleBulkDelete = () => {
    setDeleteConfirm({
      type: "document",
      id: Array.from(selectedFiles).join(","),
      name: `${selectedFiles.size} selected file${
        selectedFiles.size > 1 ? "s" : ""
      }`,
    });
  };

  // Folder drag-over for file grid area
  const [dragOverFolderId, setDragOverFolderId] = useState<string | null>(null);

  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState<{
    type: "folder" | "document";
    id: string;
    name: string;
  } | null>(null);

  const {
    documents,
    loading: docsLoading,
    error,
    loadDocuments,
    move,
    remove,
  } = useDocuments(currentFolderId);

  const {
    tasks: ingestionTasks,
    hasActiveTasks,
    drawerOpen: ingestionDrawerOpen,
    upload,
    openDrawer: openIngestionDrawer,
    closeDrawer: closeIngestionDrawer,
    cancelAutoClose,
  } = useIngestionStatus();

  // Clear selection when folder changes
  const [prevFolder, setPrevFolder] = useState(currentFolderId);
  if (prevFolder !== currentFolderId) {
    setPrevFolder(currentFolderId);
    if (selectedFiles.size > 0) {
      setSelectedFiles(new Set());
    }
  }

  // Refresh document list when ingestion tasks complete
  useEffect(() => {
    const completedCount = ingestionTasks.filter(
      (t) => t.stage === "completed",
    ).length;
    if (completedCount > 0) {
      loadDocuments();
    }
  }, [ingestionTasks, loadDocuments]);

  // Listen for new-folder event from sidebar
  useEffect(() => {
    const handler = () => setNewFolderOpen(true);
    window.addEventListener("new-folder", handler);
    return () => window.removeEventListener("new-folder", handler);
  }, []);

  // Upload one file, toast on failure. Kept as a helper so the input picker
  // and drop handler both get identical error surfacing.
  const uploadOne = useCallback(
    async (file: File) => {
      try {
        await upload(file, currentFolderId);
      } catch (err) {
        toast.show(
          `Upload failed for “${file.name}”: ${messageFromError(err)}`,
          "error",
        );
      }
    },
    [upload, currentFolderId, toast],
  );

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    if (files.length) setUploadOpen(false);
    for (const file of Array.from(files)) {
      void uploadOne(file);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      for (const file of files) {
        void uploadOne(file);
      }
    },
    [uploadOne],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  // Subfolders of the current directory for the grid. keepPreviousData keeps
  // the previous folder's children on screen while the new folder loads.
  const subFoldersQuery = useQuery(folderOptions(currentFolderId));
  const contentLoading = docsLoading || subFoldersQuery.isPending;
  const subFolders = useMemo(
    () =>
      (subFoldersQuery.data ?? []).map((f) => ({
        id: f.id,
        name: f.name,
        kind: f.kind,
      })),
    [subFoldersQuery.data],
  );

  // Breadcrumbs for the current folder (empty at root). keepPreviousData so the
  // strip doesn't blank to "Home" while the next folder's path loads.
  const breadcrumbsQuery = useQuery({
    ...breadcrumbOptions(currentFolderId ?? "none"),
    enabled: !!currentFolderId,
  });
  const breadcrumbs: Breadcrumb[] = currentFolderId
    ? (breadcrumbsQuery.data ?? [])
    : [];

  // Global drag-and-drop from OS: dim entire content area whenever the user
  // starts dragging files anywhere over the page.
  useEffect(() => {
    let counter = 0;
    const isFileDrag = (e: DragEvent) =>
      e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");

    const onEnter = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      counter++;
      setGlobalDropActive(true);
    };
    const onLeave = (e: DragEvent) => {
      if (!isFileDrag(e)) return;
      counter = Math.max(0, counter - 1);
      if (counter === 0) setGlobalDropActive(false);
    };
    const onDrop = () => {
      counter = 0;
      setGlobalDropActive(false);
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  // Filter documents by search query
  const filteredDocs = useMemo(() => {
    if (!searchQuery.trim()) return documents;
    const q = searchQuery.toLowerCase();
    return documents.filter((d) => d.source_filename.toLowerCase().includes(q));
  }, [documents, searchQuery]);

  const filteredFolders = useMemo(() => {
    if (!searchQuery.trim()) return subFolders;
    const q = searchQuery.toLowerCase();
    return subFolders.filter((f) => f.name.toLowerCase().includes(q));
  }, [subFolders, searchQuery]);

  // The current folder is the last breadcrumb; its kind decides whether the
  // repo Briefing tab is available. Non-repo folders keep the plain file view.
  const currentFolderIsRepo =
    breadcrumbs.length > 0 &&
    breadcrumbs[breadcrumbs.length - 1]?.kind === "repo";

  // Reset to the Files tab whenever we navigate to a different folder, so a
  // repo's Briefing tab never "sticks" onto the next folder we open.
  useEffect(() => {
    setFolderTab("files");
  }, [currentFolderId]);

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    try {
      await createFolder(newFolderName.trim(), currentFolderId);
      setNewFolderName("");
      setNewFolderOpen(false);
      queryClient.invalidateQueries({ queryKey: ["folders"] });
    } catch (err) {
      toast.show(`Couldn't create folder: ${messageFromError(err)}`, "error");
    }
  };

  const handleRequestDeleteFolder = useCallback(
    (folderId: string, folderName: string) => {
      setDeleteConfirm({ type: "folder", id: folderId, name: folderName });
    },
    [setDeleteConfirm],
  );

  const handleConfirmDelete = async () => {
    if (!deleteConfirm) return;
    try {
      if (deleteConfirm.type === "folder") {
        await deleteFolder(deleteConfirm.id);
        if (currentFolderId === deleteConfirm.id) {
          setCurrentFolderId(null);
        }
        queryClient.invalidateQueries({ queryKey: ["folders"] });
      } else if (deleteConfirm.id.includes(",")) {
        const filenames = deleteConfirm.id.split(",");
        const failed: string[] = [];
        for (const filename of filenames) {
          try {
            await remove(filename);
          } catch (err) {
            failed.push(`${filename}: ${messageFromError(err)}`);
          }
        }
        if (failed.length > 0) {
          toast.show(
            `Couldn't delete ${failed.length} of ${filenames.length} files (${failed[0]})`,
            "error",
          );
        }
        clearSelection();
      } else {
        await remove(deleteConfirm.name);
      }
    } catch (err) {
      toast.show(`Delete failed: ${messageFromError(err)}`, "error");
    } finally {
      setDeleteConfirm(null);
    }
  };

  const handleDownload = async (filename: string) => {
    try {
      const url = await downloadDocument(filename);
      window.open(url, "_blank");
    } catch (err) {
      toast.show(
        `Couldn't download “${filename}”: ${messageFromError(err)}`,
        "error",
      );
    }
  };

  const isEmpty =
    subFolders.length === 0 && documents.length === 0 && !hasActiveTasks;

  return (
    <Box
      className="documents-page"
      sx={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "auto",
      }}
    >
      <Box
        className="documents-header"
        sx={{ px: { xs: 2, md: 4 }, pt: 3, pb: 3 }}
      >
        <Stack
          direction="row"
          alignItems="center"
          gap={0.5}
          sx={{ mb: 2, flexWrap: "wrap" }}
          className="documents-path"
          aria-label="Folder path"
        >
          <IconButton
            size="small"
            aria-label="Root"
            onClick={() => setCurrentFolderId(null)}
          >
            <HomeIcon sx={{ fontSize: 18 }} />
          </IconButton>
          {breadcrumbs.map((bc) => (
            <Box key={bc.id} sx={{ display: "flex", alignItems: "center" }}>
              <ChevronRightIcon sx={{ fontSize: 16, color: brand.muted }} />
              <Button
                size="small"
                onMouseEnter={() => prefetchFolder(queryClient, bc.id)}
                onClick={() => setCurrentFolderId(bc.id)}
                sx={{ color: brand.muted }}
              >
                {bc.name}
              </Button>
            </Box>
          ))}
        </Stack>
        <Stack
          className="documents-heading"
          direction={{ xs: "column", sm: "row" }}
          justifyContent="space-between"
          alignItems={{ xs: "flex-start", sm: "center" }}
          gap={2}
        >
          <Box>
            <Typography
              component="h1"
              sx={{
                fontSize: { xs: 28, md: 34 },
                fontWeight: 600,
                letterSpacing: "-0.03em",
                lineHeight: 1.2,
              }}
            >
              {currentFolderId
                ? (breadcrumbs.at(-1)?.name ?? "Loading folder…")
                : "All documents"}
              {currentFolderId && (
                <NotionFolderIndicator folderId={currentFolderId} />
              )}
            </Typography>
            <Typography sx={{ mt: 1, color: brand.muted, fontSize: 16 }}>
              {currentFolderIsRepo
                ? "Project documents, briefing, and repository context."
                : "Your documents and repository knowledge."}
            </Typography>
          </Box>
          <Stack
            className="documents-actions"
            direction="row"
            gap={1.25}
            alignItems="center"
            flexWrap="nowrap"
          >
            {ingestionTasks.length > 0 && (
              <Tooltip title="Processing status">
                <IconButton size="small" onClick={openIngestionDrawer}>
                  <Badge
                    badgeContent={
                      ingestionTasks.filter(
                        (t) =>
                          !["completed", "error", "duplicate"].includes(
                            t.stage,
                          ),
                      ).length || undefined
                    }
                    color="primary"
                  >
                    <CloudUploadIcon fontSize="small" />
                  </Badge>
                </IconButton>
              </Tooltip>
            )}
            <input
              type="file"
              ref={fileInputRef}
              hidden
              multiple
              accept={ACCEPTED_TYPES}
              onChange={handleFileSelect}
            />
            <Button
              size="small"
              variant="outlined"
              className="new-folder-action"
              startIcon={<CreateNewFolderIcon fontSize="small" />}
              onClick={() => setNewFolderOpen(true)}
              sx={{ borderColor: brand.line, color: brand.muted }}
            >
              New folder
            </Button>
            <Button
              variant="contained"
              size="small"
              startIcon={<UploadFileIcon />}
              onClick={() => setUploadOpen(true)}
            >
              Upload
            </Button>
          </Stack>
        </Stack>
      </Box>
      {/* Content area */}
      <Box
        className="documents-content"
        sx={{
          flex: 1,
          minHeight: 0,
          p: { xs: 2, md: 4 },
          pt: { xs: 0, md: 0 },
          position: "relative",
        }}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        {/* Full-page drop overlay handles file uploads. */}
        <Stack
          className="upload-strip"
          direction="row"
          spacing={1}
          alignItems="center"
          sx={{
            mb: 3,
            px: 2.5,
            py: 2,
            minHeight: 80,
            border: `1px dashed ${brand.lineGlow}`,
            borderRadius: "4px",
            bgcolor: brand.surface2,
          }}
        >
          <CloudUploadIcon aria-hidden="true" sx={{ color: brand.magenta }} />
          <Typography
            sx={{
              fontFamily: fonts.body,
              fontSize: "0.8rem",
              color: brand.muted,
            }}
          >
            Drop files into this folder, or use Upload.
          </Typography>
        </Stack>

        {(error || subFoldersQuery.isError) && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error || "Couldn’t load folders. Please try again."}
          </Alert>
        )}

        {/* Repo folders get a Files | Briefing tab bar so the generated
              knowledge lives on its own tab, away from the file browser. */}
        {currentFolderIsRepo && (
          <Tabs
            className="folder-tabs"
            value={folderTab}
            onChange={(_, v) => setFolderTab(v)}
            sx={{
              mb: 3,
              minHeight: 40,
              borderBottom: `1px solid ${brand.line}`,
              "& .MuiTab-root": {
                minHeight: 40,
                textTransform: "none",
                fontFamily: fonts.display,
                fontSize: "0.9rem",
                color: brand.muted,
                "&.Mui-selected": { color: brand.text },
              },
              "& .MuiTabs-indicator": { backgroundColor: brand.magenta },
            }}
          >
            <Tab value="files" label="Files" />
            <Tab value="briefing" label="Briefing" />
            <Tab value="status" label="Status" />
            <Tab value="learnings" label="Learnings" />
          </Tabs>
        )}

        {(!currentFolderIsRepo || folderTab === "files") && (
          <Stack
            direction="row"
            alignItems="center"
            gap={1.5}
            className="documents-toolbar"
            sx={{ mb: 3, flexWrap: "wrap" }}
          >
            <TextField
              size="small"
              className="documents-search"
              placeholder="Search in this folder…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon sx={{ fontSize: 18, color: brand.muted }} />
                  </InputAdornment>
                ),
                endAdornment: searchQuery ? (
                  <InputAdornment position="end">
                    <IconButton
                      aria-label="Clear search"
                      size="small"
                      onClick={() => setSearchQuery("")}
                    >
                      <CloseIcon sx={{ fontSize: 16 }} />
                    </IconButton>
                  </InputAdornment>
                ) : null,
              }}
              sx={{
                flex: 1,
                maxWidth: { xs: "none", sm: 380 },
                flexBasis: { xs: "100%", sm: "auto" },
                minWidth: 0,
                "& .MuiOutlinedInput-root": {
                  fontFamily: fonts.body,
                  fontSize: "0.85rem",
                },
              }}
            />

            <ToggleButtonGroup
              value={viewMode}
              exclusive
              size="small"
              onChange={(_, v) => v && setViewMode(v)}
              sx={{
                border: `1px solid ${brand.lineGlow}`,
                borderRadius: "3px",
                overflow: "hidden",
                "& .MuiToggleButton-root": {
                  border: 0,
                  borderRadius: 0,
                  color: brand.muted,
                  px: "10px",
                  py: "6px",
                  "&.Mui-selected": {
                    color: brand.magenta,
                    bgcolor: alpha(brand.magenta, 0.14),
                  },
                },
              }}
            >
              <ToggleButton value="list" aria-label="List view">
                <ViewListIcon fontSize="small" />
              </ToggleButton>
              <ToggleButton value="grid" aria-label="Grid view">
                <GridViewIcon fontSize="small" />
              </ToggleButton>
            </ToggleButtonGroup>
          </Stack>
        )}
        {/* Sub-folders grid */}
        {(!currentFolderIsRepo || folderTab === "files") &&
          filteredFolders.length > 0 && (
            <Box>
              <Box
                className="folder-grid"
                sx={{
                  display: "grid",
                  gridTemplateColumns:
                    "repeat(auto-fill, minmax(min(100%, 220px), 1fr))",
                  gap: viewMode === "grid" ? 1.5 : 0.5,
                }}
              >
                {filteredFolders.map((folder) => {
                  const folderColor = brand.cyan;
                  return (
                    <CornerCard
                      className="folder-card"
                      key={folder.id}
                      color={
                        dragOverFolderId === folder.id
                          ? brand.magenta
                          : folderColor
                      }
                      onContextMenu={(e) => {
                        e.preventDefault();
                        setIntegrationsTarget({
                          id: folder.id,
                          name: folder.name,
                          kind: folder.kind,
                        });
                      }}
                      onDragOver={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDragOverFolderId(folder.id);
                      }}
                      onDragLeave={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDragOverFolderId((prev) =>
                          prev === folder.id ? null : prev,
                        );
                      }}
                      onDrop={(e: React.DragEvent) => {
                        e.preventDefault();
                        e.stopPropagation();
                        setDragOverFolderId(null);
                        setDragOver(false);
                        const docFilename = e.dataTransfer.getData(
                          "application/x-document-filename",
                        );
                        if (docFilename) {
                          move(docFilename, folder.id);
                          return;
                        }
                        const droppedFiles = Array.from(e.dataTransfer.files);
                        for (const f of droppedFiles) {
                          upload(f, folder.id);
                        }
                      }}
                      sx={{
                        height: 104,
                        px: viewMode === "grid" ? "16px" : "14px",
                        position: "relative",
                        cursor: "pointer",
                        display: "flex",
                        flexDirection: "row",
                        alignItems: "center",
                        gap: "12px",
                        bgcolor:
                          dragOverFolderId === folder.id
                            ? alpha(brand.magenta, 0.1)
                            : brand.surface,
                        border: `1px solid ${folderColor}88`,
                        transition: "all 0.15s ease",
                        "&:hover": {
                          borderColor: folderColor,
                          boxShadow: `0 0 16px ${folderColor}28`,
                          bgcolor: brand.surface,
                          "& .folder-card-delete": { opacity: 1 },
                        },
                      }}
                      onMouseEnter={() =>
                        prefetchFolder(queryClient, folder.id)
                      }
                      onFocus={() => prefetchFolder(queryClient, folder.id)}
                      onClick={() => setCurrentFolderId(folder.id)}
                    >
                      <IconButton
                        className="folder-card-delete"
                        size="small"
                        title="Chat with this folder"
                        aria-label={`Chat with ${folder.name}`}
                        sx={{
                          position: "absolute",
                          top: 6,
                          right: 28,
                          opacity: 1,
                          transition: "opacity 0.15s",
                          p: 0.25,
                          bgcolor: alpha("#000000", 0.3),
                          "&:hover": { bgcolor: alpha(brand.magenta, 0.3) },
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(
                            `/?scope_folder=${folder.id}` +
                              `&scope_name=${encodeURIComponent(folder.name)}`,
                          );
                        }}
                      >
                        <ChatBubbleOutlineIcon sx={{ fontSize: 14 }} />
                      </IconButton>
                      <IconButton
                        className="folder-card-delete"
                        size="small"
                        aria-label={`Delete ${folder.name}`}
                        sx={{
                          position: "absolute",
                          top: 6,
                          right: 6,
                          opacity: 1,
                          transition: "opacity 0.15s",
                          p: 0.25,
                          bgcolor: alpha("#000000", 0.3),
                          "&:hover": { bgcolor: alpha(brand.red, 0.3) },
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRequestDeleteFolder(folder.id, folder.name);
                        }}
                      >
                        <DeleteIcon sx={{ fontSize: 14 }} />
                      </IconButton>
                      {folder.kind === "repo" ? (
                        <AccountTreeIcon
                          sx={{
                            fontSize: 24,
                            color: brand.cyan,
                            filter: "none",
                            flexShrink: 0,
                          }}
                        />
                      ) : (
                        <FolderIcon
                          sx={{
                            fontSize: 24,
                            color: brand.cyan,
                            filter: "none",
                            flexShrink: 0,
                          }}
                        />
                      )}
                      <Box
                        sx={{
                          display: "flex",
                          flexDirection: "column",
                          gap: "2px",
                          minWidth: 0,
                        }}
                      >
                        <Typography
                          className="folder-title"
                          noWrap
                          sx={{
                            fontWeight: 500,
                            fontSize: "0.875rem",
                            color: brand.text,
                          }}
                        >
                          {folder.name}
                          <NotionFolderIndicator folderId={folder.id} />
                        </Typography>
                        <Typography
                          sx={{
                            fontFamily: fonts.mono,
                            fontSize: "0.8125rem",
                            letterSpacing: 0,
                            color: brand.muted,
                            textTransform: "none",
                          }}
                        >
                          {folder.kind === "repo" ? "Repository" : "Folder"}
                        </Typography>
                      </Box>
                    </CornerCard>
                  );
                })}
              </Box>
            </Box>
          )}

        {/* Repos surface their generated knowledge on the Briefing tab,
              placed BELOW the folder grid so subfolders sit at the top. Non-repo
              folders have no summary/briefing — only repos do now. */}
        {currentFolderIsRepo && folderTab === "briefing" && currentFolderId && (
          <>
            <BriefingPanel folderId={currentFolderId} />
            <DocumentationPanel folderId={currentFolderId} />
          </>
        )}

        {currentFolderIsRepo && folderTab === "status" && currentFolderId && (
          <StatusPanel folderId={currentFolderId} />
        )}
        {currentFolderIsRepo &&
          folderTab === "learnings" &&
          currentFolderId && (
            <LearningsPanel key={currentFolderId} folderId={currentFolderId} />
          )}

        {/* Documents grid */}
        {(!currentFolderIsRepo || folderTab === "files") &&
          filteredDocs.length > 0 && (
            <Box>
              <Typography
                className="files-heading"
                variant="overline"
                sx={{
                  fontFamily: fonts.mono,
                  color: brand.muted,
                  mb: 1.25,
                  display: "block",
                  letterSpacing: 0,
                  fontSize: "0.8125rem",
                }}
              >
                <Box
                  component="span"
                  sx={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 0.5,
                  }}
                >
                  Files <Chip size="small" label={filteredDocs.length} />
                </Box>
                <Typography
                  component="span"
                  sx={{ fontSize: 12, color: brand.muted }}
                >
                  Updated most recently
                </Typography>
              </Typography>
              <Box
                className="file-table"
                role={viewMode === "list" ? "table" : undefined}
                aria-label="Files"
                sx={{
                  border:
                    viewMode === "list" ? `1px solid ${brand.line}` : undefined,
                  borderRadius: 2,
                  overflow: "hidden",
                }}
              >
                {viewMode === "list" && (
                  <Box
                    role="row"
                    className="file-table-header"
                    sx={{
                      display: { xs: "none", md: "grid" },
                      gridTemplateColumns: "minmax(0,1fr) 160px 180px 44px",
                      px: 2.5,
                      py: 1.5,
                      bgcolor: brand.surface2,
                      borderBottom: `1px solid ${brand.line}`,
                      color: brand.muted,
                      fontSize: 14,
                    }}
                  >
                    <span role="columnheader">Name</span>
                    <span className="source-heading" role="columnheader">
                      Source
                    </span>
                    <span role="columnheader">Last updated</span>
                    <span />
                  </Box>
                )}
                <Box
                  role={viewMode === "list" ? "rowgroup" : undefined}
                  sx={{
                    display: viewMode === "grid" ? "grid" : "block",
                    gridTemplateColumns:
                      "repeat(auto-fill,minmax(min(100%,220px),1fr))",
                    gap: 1.5,
                  }}
                >
                  {filteredDocs.map((doc) => (
                    <DocumentCard
                      key={doc.source_filename}
                      doc={doc}
                      selected={selectedFiles.has(doc.source_filename)}
                      onSelect={toggleFileSelect}
                      onDelete={(filename) => {
                        setDeleteConfirm({
                          type: "document",
                          id: filename,
                          name: filename,
                        });
                      }}
                      onDownload={handleDownload}
                      onMove={(filename, folderId) => {
                        move(filename, folderId);
                      }}
                      onOpen={(filename) => setViewerFile(filename)}
                      onChat={(filename) =>
                        navigate(
                          `/?scope_file=${encodeURIComponent(filename)}` +
                            (currentFolderId
                              ? `&scope_folder=${currentFolderId}`
                              : ""),
                        )
                      }
                      variant={viewMode}
                    />
                  ))}
                </Box>
              </Box>
              <Typography sx={{ mt: 2, color: brand.muted, fontSize: 13 }}>
                {filteredDocs.length} documents · Original creation dates are
                preserved when content is updated.
              </Typography>
            </Box>
          )}

        {/* Empty / no-results state */}
        {/* Cold load: show skeletons instead of flashing the empty state while
            this folder's data is fetched for the first time (a revisit hits the
            cache and skips this entirely). */}
        {(!currentFolderIsRepo || folderTab === "files") &&
          contentLoading &&
          documents.length === 0 &&
          subFolders.length === 0 && (
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
                gap: "14px",
                mt: 1,
              }}
            >
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton
                  key={i}
                  variant="rounded"
                  height={92}
                  sx={{
                    bgcolor: alpha(brand.violet, 0.08),
                    borderRadius: "10px",
                  }}
                />
              ))}
            </Box>
          )}

        {(!currentFolderIsRepo || folderTab === "files") &&
          isEmpty &&
          !contentLoading &&
          !error &&
          !subFoldersQuery.isError && (
            <Stack
              alignItems="center"
              spacing={2}
              sx={{ mt: 10, textAlign: "center" }}
            >
              <Box
                sx={{
                  width: 72,
                  height: 72,
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  bgcolor: alpha(brand.violet, 0.1),
                  border: `1px solid ${alpha(brand.violet, 0.25)}`,
                }}
              >
                <CloudUploadIcon sx={{ fontSize: 32, color: brand.violet2 }} />
              </Box>
              <Stack alignItems="center" spacing={0.5}>
                <Typography
                  sx={{
                    fontFamily: fonts.display,
                    fontWeight: 700,
                    fontSize: "1.15rem",
                    color: brand.text,
                  }}
                >
                  {currentFolderId
                    ? "This folder is empty"
                    : "Your corpus is empty"}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: fonts.body,
                    fontSize: "0.88rem",
                    color: brand.muted,
                    maxWidth: { xs: "none", sm: 380 },
                    flexBasis: { xs: "100%", sm: "auto" },
                    minWidth: 0,
                  }}
                >
                  Drop files anywhere on this page, click Upload above, or
                  record audio directly.
                </Typography>
                {currentFolderId && (
                  <Typography
                    sx={{
                      fontFamily: fonts.body,
                      fontSize: "0.8rem",
                      color: brand.violet2,
                      maxWidth: 420,
                      mt: 1,
                    }}
                  >
                    Tip: docs you add here (or a Notion sync) enrich this repo's
                    briefing — <code>kioku init</code> folds them in, so it
                    understands your whole ecosystem, not just the code.
                  </Typography>
                )}
              </Stack>
              <Button
                variant="contained"
                size="small"
                startIcon={<UploadFileIcon />}
                onClick={() => fileInputRef.current?.click()}
              >
                Upload your first file
              </Button>
            </Stack>
          )}

        {/* Search returned nothing */}
        {(!currentFolderIsRepo || folderTab === "files") &&
          !isEmpty &&
          searchQuery &&
          !contentLoading &&
          filteredFolders.length === 0 &&
          filteredDocs.length === 0 && (
            <Stack
              alignItems="center"
              spacing={1.5}
              sx={{ mt: 8, textAlign: "center" }}
            >
              <SearchIcon sx={{ fontSize: 40, color: brand.muted }} />
              <Typography
                sx={{
                  fontFamily: fonts.display,
                  fontWeight: 600,
                  color: brand.text,
                }}
              >
                No matches for "{searchQuery}"
              </Typography>
              <Button size="small" onClick={() => setSearchQuery("")}>
                Clear search
              </Button>
            </Stack>
          )}
      </Box>

      {/* Full-page drop overlay when dragging files anywhere */}
      {globalDropActive && (
        <Box
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onDragLeave={handleDragLeave}
          sx={{
            position: "fixed",
            inset: 0,
            zIndex: 1500,
            pointerEvents: "auto",
            backdropFilter: "blur(6px)",
            WebkitBackdropFilter: "blur(6px)",
            bgcolor: alpha(brand.ink, 0.75),
            display: "grid",
            placeItems: "center",
            transition: "opacity 0.15s ease-out",
          }}
          data-testid="global-drop-overlay"
        >
          <Stack
            alignItems="center"
            spacing={2}
            sx={{
              border: `2px dashed ${brand.violet2}`,
              borderRadius: 4,
              px: 8,
              py: 6,
              bgcolor: alpha(brand.violet, 0.08),
              minWidth: 460,
            }}
          >
            <Box
              sx={{
                width: 80,
                height: 104,
                borderRadius: "50%",
                display: "grid",
                placeItems: "center",
                background: `radial-gradient(circle at 30% 30%, ${brand.violet2} 0%, ${brand.violetDeep} 100%)`,
                boxShadow: `0 12px 40px ${alpha(brand.violet, 0.6)}`,
              }}
            >
              <CloudUploadIcon sx={{ fontSize: 40, color: "#fff" }} />
            </Box>
            <Typography
              sx={{
                fontFamily: fonts.display,
                fontWeight: 700,
                fontSize: "1.5rem",
                color: brand.text,
              }}
            >
              Drop to upload
            </Typography>
            <Typography
              sx={{
                fontFamily: fonts.body,
                fontSize: "0.9rem",
                color: brand.muted,
              }}
            >
              Files will land in{" "}
              {breadcrumbs.length
                ? `"${breadcrumbs[breadcrumbs.length - 1]!.name}"`
                : "the root folder"}
            </Typography>
          </Stack>
        </Box>
      )}

      {/* Bulk action bar */}
      {selectedFiles.size > 0 && (
        <Paper
          elevation={8}
          sx={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            alignItems: "center",
            gap: 2,
            px: 3,
            py: 1.5,
            borderRadius: 3,
            bgcolor: alpha("#1e1e2e", 0.95),
            border: 1,
            borderColor: alpha("#FF2E93", 0.3),
            backdropFilter: "blur(12px)",
            zIndex: 1200,
          }}
        >
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            {selectedFiles.size} selected
          </Typography>
          <Button
            size="small"
            startIcon={<DriveFileMoveIcon />}
            onClick={() => setBulkMoveOpen(true)}
            sx={{ textTransform: "none" }}
          >
            Move
          </Button>
          <Button
            size="small"
            startIcon={<DeleteIcon />}
            color="error"
            onClick={handleBulkDelete}
            sx={{ textTransform: "none" }}
          >
            Delete
          </Button>
          <IconButton size="small" onClick={clearSelection}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Paper>
      )}

      {/* Bulk Move Dialog */}
      <MoveDialog
        open={bulkMoveOpen}
        title={`Move ${selectedFiles.size} file${
          selectedFiles.size > 1 ? "s" : ""
        }`}
        onClose={() => setBulkMoveOpen(false)}
        onSelect={handleBulkMove}
      />

      {/* New Folder Dialog */}
      <Dialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        maxWidth={false}
        fullWidth
        PaperProps={{ sx: { maxWidth: 750, borderRadius: "8px" } }}
      >
        <DialogTitle sx={{ p: "24px 26px", fontSize: 21 }}>
          Upload documents
        </DialogTitle>
        <DialogContent sx={{ px: "26px", pb: 3 }}>
          <Box
            onDragEnter={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
            onDragOver={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
            onDrop={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setGlobalDropActive(false);
              const files = Array.from(event.dataTransfer.files);
              if (files.length) setUploadOpen(false);
              for (const file of files) void uploadOne(file);
            }}
            sx={{
              border: `1px dashed ${brand.lineGlow}`,
              borderRadius: "5px",
              p: "32px 20px",
              textAlign: "center",
              bgcolor: brand.ink,
            }}
          >
            <UploadFileIcon
              sx={{ color: brand.muted, fontSize: 22, mb: 1.5 }}
            />
            <Typography sx={{ fontSize: 17, fontWeight: 600, mb: 1 }}>
              Drop files here
            </Typography>
            <Typography sx={{ fontSize: 14, color: brand.muted, mb: 2 }}>
              PDF, Markdown, Word, text, images, and audio.
            </Typography>
            <Button
              variant="outlined"
              onClick={() => fileInputRef.current?.click()}
            >
              Choose files
            </Button>
          </Box>
          <Typography
            component="label"
            htmlFor="upload-destination"
            sx={{ display: "block", fontSize: 14, mt: 3, mb: 1 }}
          >
            Destination folder
          </Typography>
          <TextField
            id="upload-destination"
            size="small"
            fullWidth
            value={
              breadcrumbs.length
                ? breadcrumbs.map((item) => item.name).join(" / ")
                : "All documents"
            }
            slotProps={{
              input: { readOnly: true },
              htmlInput: { "aria-label": "Destination folder" },
            }}
            sx={{ "& .MuiOutlinedInput-root": { height: 44 } }}
          />
          <Typography sx={{ fontSize: 13, color: brand.muted, mt: 1.5 }}>
            Files are added to this folder. Processing progress appears in the
            upload status panel.
          </Typography>
        </DialogContent>
        <DialogActions sx={{ px: "26px", pb: 3, justifyContent: "flex-start" }}>
          <Button variant="contained" onClick={() => setUploadOpen(false)}>
            Close
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={newFolderOpen}
        onClose={() => setNewFolderOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>New Folder</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            label="Folder name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreateFolder();
            }}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setNewFolderOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreateFolder}
            disabled={!newFolderName.trim()}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>

      {/* Ingestion Drawer */}
      <IngestionDrawer
        open={ingestionDrawerOpen}
        tasks={ingestionTasks}
        onClose={closeIngestionDrawer}
        onInteract={cancelAutoClose}
      />

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteConfirm !== null}
        onClose={() => setDeleteConfirm(null)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>
          Delete {deleteConfirm?.type === "folder" ? "Folder" : "Document"}
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            {deleteConfirm?.type === "folder"
              ? `Are you sure you want to delete the folder "${deleteConfirm.name}"? All subfolders will be deleted and documents inside will be moved to the root.`
              : `Are you sure you want to delete "${deleteConfirm?.name}"? All chunks associated with this document will be permanently removed.`}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteConfirm(null)}>Cancel</Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleConfirmDelete}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      <FolderIntegrationsDialog
        open={!!integrationsTarget}
        folder={integrationsTarget}
        onClose={() => setIntegrationsTarget(null)}
      />

      {/* Document viewer drawer — opened by clicking a file card */}
      <DocumentViewerDrawer
        filename={viewerFile}
        folderId={currentFolderId}
        onClose={() => setViewerFile(null)}
      />
    </Box>
  );
}
