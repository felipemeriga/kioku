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
} from "@mui/material";
import { useSearchParams } from "react-router-dom";
import { keyframes } from "@mui/system";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import DeleteIcon from "@mui/icons-material/Delete";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import FolderIcon from "@mui/icons-material/Folder";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import MicIcon from "@mui/icons-material/Mic";
import DriveFileMoveIcon from "@mui/icons-material/DriveFileMove";
import CloseIcon from "@mui/icons-material/Close";
import StopIcon from "@mui/icons-material/Stop";
import SearchIcon from "@mui/icons-material/Search";
import GridViewIcon from "@mui/icons-material/GridView";
import ViewListIcon from "@mui/icons-material/ViewList";
import CreateNewFolderIcon from "@mui/icons-material/CreateNewFolder";
import HomeIcon from "@mui/icons-material/Home";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { useDocuments } from "../hooks/useDocuments";
import { useIngestionStatus } from "../hooks/useIngestionStatus";
import {
  createFolder,
  fetchBreadcrumbs,
  fetchFolders,
  deleteFolder,
  downloadDocument,
} from "../lib/api";
import type { Breadcrumb } from "../lib/api";
import DocumentCard from "../components/DocumentCard";
import MoveDialog from "../components/MoveDialog";
import IngestionDrawer from "../components/IngestionDrawer";
import FolderSummaryPanel from "../components/FolderSummaryPanel";
import FolderIntegrationsDialog from "../components/FolderIntegrationsDialog";
import { useToast, messageFromError } from "../components/ToastProvider";
import { brand, fonts } from "../theme";

const ACCEPTED_TYPES =
  ".txt,.text,.md,.markdown,.pdf,.docx,.html,.htm,.json,.yaml,.yml,.png,.jpg,.jpeg,.mp3,.webm,.m4a";

const pulse = keyframes`
  0% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.15); }
  100% { opacity: 1; transform: scale(1); }
`;
export default function DocumentsPage() {
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [, setDragOver] = useState(false);
  const [integrationsTarget, setIntegrationsTarget] = useState<
    { id: string; name: string; kind?: "folder" | "repo" } | null
  >(null);
  const [globalDropActive, setGlobalDropActive] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [breadcrumbs, setBreadcrumbs] = useState<Breadcrumb[]>([]);

  // Audio recording
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);

  // Folder navigation via URL search params (shared with ContextPanel)
  const [searchParams, setSearchParams] = useSearchParams();
  const currentFolderId = searchParams.get("folder") || null;
  const setCurrentFolderId = useCallback(
    (id: string | null) => {
      setSearchParams(id ? { folder: id } : {}, { replace: true });
    },
    [setSearchParams]
  );
  const [newFolderOpen, setNewFolderOpen] = useState(false);
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
      name: `${selectedFiles.size} selected file${selectedFiles.size > 1 ? "s" : ""}`,
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

  const { documents, error, loadDocuments, move, remove } =
    useDocuments(currentFolderId);

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
      (t) => t.stage === "completed"
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

  // Recording timer
  useEffect(() => {
    if (!isRecording) return;
    const id = setInterval(() => setRecordingTime((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [isRecording]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mimeType = MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : undefined;
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      mediaRecorderRef.current = recorder;

      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: recorder.mimeType });
        const ext = recorder.mimeType.includes("webm") ? "webm" : "mp4";
        const file = new File([blob], `recording-${Date.now()}.${ext}`, {
          type: blob.type,
        });
        void uploadOne(file);
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        mediaRecorderRef.current = null;
      };
      recorder.start();
      setRecordingTime(0);
      setIsRecording(true);
    } catch {
      toast.show(
        "Microphone access denied — please allow microphone permissions in your browser.",
        "warning",
      );
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  };

  const handleMicClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
      .toString()
      .padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

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

  const [subFolders, setSubFolders] = useState<
    { id: string; name: string; kind?: "folder" | "repo" }[]
  >(
    []
  );

  // Load subfolders of current directory for the grid view.
  // Non-critical: page still renders. Logged so devs see repeated failures.
  const loadSubFolders = useCallback(() => {
    fetchFolders(currentFolderId)
      .then((data) =>
        setSubFolders(data.map((f) => ({ id: f.id, name: f.name, kind: f.kind })))
      )
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn("[DocumentsPage] failed to load subfolders:", err);
      });
  }, [currentFolderId]);

  useEffect(() => {
    loadSubFolders();
  }, [loadSubFolders]);

  // Load breadcrumbs for the current folder. Non-critical — falling back to
  // empty means the breadcrumb strip shows just Home. Surfaced only via toast
  // if the failure is not a network transient (network is common while
  // uploading, so we don't spam on those).
  useEffect(() => {
    if (!currentFolderId) {
      setBreadcrumbs([]);
      return;
    }
    fetchBreadcrumbs(currentFolderId)
      .then(setBreadcrumbs)
      .catch((err) => {
        setBreadcrumbs([]);
        // eslint-disable-next-line no-console
        console.warn("[DocumentsPage] failed to load breadcrumbs:", err);
      });
  }, [currentFolderId]);

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
    return documents.filter((d) =>
      d.source_filename.toLowerCase().includes(q)
    );
  }, [documents, searchQuery]);

  const filteredFolders = useMemo(() => {
    if (!searchQuery.trim()) return subFolders;
    const q = searchQuery.toLowerCase();
    return subFolders.filter((f) => f.name.toLowerCase().includes(q));
  }, [subFolders, searchQuery]);

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    try {
      await createFolder(newFolderName.trim(), currentFolderId);
      setNewFolderName("");
      setNewFolderOpen(false);
      loadSubFolders();
      window.dispatchEvent(new CustomEvent("folders-changed"));
    } catch (err) {
      toast.show(`Couldn't create folder: ${messageFromError(err)}`, "error");
    }
  };

  const handleRequestDeleteFolder = useCallback(
    (folderId: string, folderName: string) => {
      setDeleteConfirm({ type: "folder", id: folderId, name: folderName });
    },
    [setDeleteConfirm]
  );

  const handleConfirmDelete = async () => {
    if (!deleteConfirm) return;
    try {
      if (deleteConfirm.type === "folder") {
        await deleteFolder(deleteConfirm.id);
        if (currentFolderId === deleteConfirm.id) {
          setCurrentFolderId(null);
        }
        loadSubFolders();
        window.dispatchEvent(new CustomEvent("folders-changed"));
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
      sx={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
      }}
    >
        {/* Toolbar */}
        <Box
          sx={{
            px: 3,
            pt: 2,
            pb: 1.5,
            display: "flex",
            flexDirection: "column",
            gap: 1.25,
            borderBottom: `1px solid ${brand.line}`,
            bgcolor: alpha(brand.surface2, 0.4),
          }}
        >
          {/* Breadcrumb row */}
          <Stack direction="row" alignItems="center" spacing={0.75} sx={{ flexWrap: "wrap" }}>
            <IconButton
              size="small"
              onClick={() => setCurrentFolderId(null)}
              sx={{
                p: 0.5,
                color: currentFolderId ? brand.muted : brand.violet2,
                "&:hover": { color: brand.violet2, bgcolor: alpha(brand.violet, 0.1) },
              }}
              aria-label="Root"
            >
              <HomeIcon fontSize="small" />
            </IconButton>
            {breadcrumbs.map((bc, i) => {
              const isLast = i === breadcrumbs.length - 1;
              return (
                <Stack key={bc.id} direction="row" alignItems="center" spacing={0.25}>
                  <ChevronRightIcon sx={{ fontSize: 16, color: brand.muted }} />
                  {isLast ? (
                    <Typography
                      sx={{
                        fontFamily: fonts.display,
                        fontWeight: 700,
                        fontSize: "1rem",
                        color: brand.text,
                        letterSpacing: "-0.01em",
                      }}
                    >
                      {bc.name}
                    </Typography>
                  ) : (
                    <Button
                      variant="text"
                      size="small"
                      onClick={() => setCurrentFolderId(bc.id)}
                      sx={{
                        minWidth: 0,
                        px: 0.75,
                        py: 0.25,
                        color: brand.muted,
                        fontFamily: fonts.display,
                        fontSize: "0.9rem",
                        "&:hover": { color: brand.violet2 },
                      }}
                    >
                      {bc.name}
                    </Button>
                  )}
                </Stack>
              );
            })}
            {breadcrumbs.length === 0 && (
              <Typography
                sx={{
                  fontFamily: fonts.display,
                  fontWeight: 700,
                  fontSize: "1rem",
                  color: brand.text,
                  ml: 0.5,
                  letterSpacing: "-0.01em",
                }}
              >
                All Documents
              </Typography>
            )}
            {(filteredDocs.length > 0 || filteredFolders.length > 0) && (
              <Chip
                size="small"
                label={`${filteredFolders.length + filteredDocs.length} items`}
                sx={{
                  ml: 1.25,
                  height: 22,
                  fontFamily: fonts.mono,
                  fontSize: "0.65rem",
                  letterSpacing: "0.08em",
                  bgcolor: alpha(brand.cyan, 0.08),
                  color: brand.cyan,
                  border: `1px solid ${alpha(brand.cyan, 0.3)}`,
                }}
              />
            )}
          </Stack>

          {/* Actions row */}
          <Stack direction="row" alignItems="center" spacing={1.25}>
            <TextField
              size="small"
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
                    <IconButton size="small" onClick={() => setSearchQuery("")}>
                      <CloseIcon sx={{ fontSize: 16 }} />
                    </IconButton>
                  </InputAdornment>
                ) : null,
              }}
              sx={{
                flex: 1,
                maxWidth: 380,
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
                "& .MuiToggleButton-root": {
                  border: `1px solid ${brand.line}`,
                  color: brand.muted,
                  px: 1,
                  py: 0.5,
                  "&.Mui-selected": {
                    color: brand.violet2,
                    bgcolor: alpha(brand.violet, 0.15),
                  },
                },
              }}
            >
              <ToggleButton value="grid" aria-label="Grid view">
                <GridViewIcon fontSize="small" />
              </ToggleButton>
              <ToggleButton value="list" aria-label="List view">
                <ViewListIcon fontSize="small" />
              </ToggleButton>
            </ToggleButtonGroup>

            <Box sx={{ flex: 1 }} />

            {ingestionTasks.length > 0 && (
              <Tooltip title="Processing status">
                <IconButton size="small" onClick={openIngestionDrawer}>
                  <Badge
                    badgeContent={
                      ingestionTasks.filter(
                        (t) => !["completed", "error", "duplicate"].includes(t.stage)
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
              onClick={() => fileInputRef.current?.click()}
            >
              Upload
            </Button>
          </Stack>
        </Box>

        {/* Content area */}
        <Box
          sx={{ flex: 1, overflow: "auto", p: 3, position: "relative" }}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          {/* Small recorder chip — full-page drop overlay handles file uploads */}
          <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            sx={{ mb: 2.5, color: brand.muted }}
          >
            <IconButton
              onClick={handleMicClick}
              size="small"
              sx={{
                bgcolor: isRecording ? alpha("#ef4444", 0.2) : alpha(brand.violet, 0.1),
                border: `1px solid ${isRecording ? alpha("#ef4444", 0.5) : brand.line}`,
                color: isRecording ? "#ef4444" : brand.violet2,
                "&:hover": {
                  bgcolor: isRecording ? alpha("#ef4444", 0.3) : alpha(brand.violet, 0.2),
                },
              }}
            >
              {isRecording ? <StopIcon fontSize="small" /> : <MicIcon fontSize="small" />}
            </IconButton>
            {isRecording ? (
              <Stack direction="row" spacing={0.75} alignItems="center">
                <Box
                  sx={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    bgcolor: "#ef4444",
                    animation: `${pulse} 1.2s ease-in-out infinite`,
                  }}
                />
                <Typography sx={{ color: "#ef4444", fontFamily: fonts.mono, fontSize: "0.85rem" }}>
                  {formatTime(recordingTime)}
                </Typography>
              </Stack>
            ) : (
              <Typography sx={{ fontFamily: fonts.body, fontSize: "0.8rem" }}>
                Record audio · or drop files anywhere on this page
              </Typography>
            )}
          </Stack>

          {currentFolderId && (
            <FolderSummaryPanel
              folderId={currentFolderId}
              folderName={
                breadcrumbs.length > 0
                  ? breadcrumbs[breadcrumbs.length - 1].name
                  : "This folder"
              }
            />
          )}

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {/* Sub-folders grid */}
          {filteredFolders.length > 0 && (
            <Box sx={{ mb: 3 }}>
              <Typography
                variant="overline"
                sx={{
                  fontFamily: fonts.mono,
                  color: brand.muted,
                  mb: 1.25,
                  display: "block",
                  letterSpacing: "0.28em",
                  fontSize: "0.62rem",
                }}
              >
                FOLDERS · {filteredFolders.length}
              </Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns:
                    viewMode === "grid"
                      ? "repeat(auto-fill, minmax(160px, 1fr))"
                      : "1fr",
                  gap: 1.5,
                }}
              >
                {filteredFolders.map((folder) => (
                  <Paper
                    key={folder.id}
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
                        prev === folder.id ? null : prev
                      );
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setDragOverFolderId(null);
                      setDragOver(false);
                      const docFilename = e.dataTransfer.getData(
                        "application/x-document-filename"
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
                      p: 1.5,
                      position: "relative",
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: 0.5,
                      borderRadius: 2.5,
                      overflow: "hidden",
                      bgcolor:
                        dragOverFolderId === folder.id
                          ? alpha("#FF2E93", 0.12)
                          : alpha("#1e1e2e", 0.4),
                      border: `1px solid ${
                        dragOverFolderId === folder.id
                          ? alpha("#FF2E93", 0.5)
                          : alpha("#ffffff", 0.04)
                      }`,
                      transition: "all 0.15s ease",
                      "&:hover": {
                        transform: "translateY(-1px)",
                        borderColor: alpha("#FF2E93", 0.25),
                        boxShadow: `0 4px 16px ${alpha("#FF2E93", 0.1)}`,
                        "& .folder-card-delete": { opacity: 1 },
                      },
                    }}
                    onClick={() => setCurrentFolderId(folder.id)}
                  >
                    <IconButton
                      className="folder-card-delete"
                      size="small"
                      sx={{
                        position: "absolute",
                        top: 6,
                        right: 6,
                        opacity: 0,
                        transition: "opacity 0.15s",
                        p: 0.25,
                        bgcolor: alpha("#000000", 0.3),
                        "&:hover": { bgcolor: alpha("#ef4444", 0.3) },
                      }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRequestDeleteFolder(folder.id, folder.name);
                      }}
                    >
                      <DeleteIcon sx={{ fontSize: 14 }} />
                    </IconButton>
                    {folder.kind === "repo" ? (
                      <AccountTreeIcon sx={{ fontSize: 36, color: "#06b6d4" }} />
                    ) : (
                      <FolderIcon sx={{ fontSize: 36, color: "#FF2E93" }} />
                    )}
                    <Typography
                      variant="caption"
                      noWrap
                      sx={{
                        maxWidth: "100%",
                        fontWeight: 500,
                        textAlign: "center",
                      }}
                    >
                      {folder.name}
                    </Typography>
                  </Paper>
                ))}
              </Box>
            </Box>
          )}

          {/* Documents grid */}
          {filteredDocs.length > 0 && (
            <Box>
              <Typography
                variant="overline"
                sx={{
                  fontFamily: fonts.mono,
                  color: brand.muted,
                  mb: 1.25,
                  display: "block",
                  letterSpacing: "0.28em",
                  fontSize: "0.62rem",
                }}
              >
                FILES · {filteredDocs.length}
              </Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns:
                    viewMode === "grid"
                      ? "repeat(auto-fill, minmax(220px, 1fr))"
                      : "1fr",
                  gap: 1.25,
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
                  />
                ))}
              </Box>
            </Box>
          )}

          {/* Empty / no-results state */}
          {isEmpty && (
            <Stack alignItems="center" spacing={2} sx={{ mt: 10, textAlign: "center" }}>
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
                <Typography sx={{ fontFamily: fonts.display, fontWeight: 700, fontSize: "1.15rem", color: brand.text }}>
                  {currentFolderId ? "This folder is empty" : "Your corpus is empty"}
                </Typography>
                <Typography sx={{ fontFamily: fonts.body, fontSize: "0.88rem", color: brand.muted, maxWidth: 380 }}>
                  Drop files anywhere on this page, click Upload above, or record audio directly.
                </Typography>
              </Stack>
              <Button variant="contained" size="small" startIcon={<UploadFileIcon />} onClick={() => fileInputRef.current?.click()}>
                Upload your first file
              </Button>
            </Stack>
          )}

          {/* Search returned nothing */}
          {!isEmpty && searchQuery && filteredFolders.length === 0 && filteredDocs.length === 0 && (
            <Stack alignItems="center" spacing={1.5} sx={{ mt: 8, textAlign: "center" }}>
              <SearchIcon sx={{ fontSize: 40, color: brand.muted }} />
              <Typography sx={{ fontFamily: fonts.display, fontWeight: 600, color: brand.text }}>
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
                  height: 80,
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
              <Typography sx={{ fontFamily: fonts.body, fontSize: "0.9rem", color: brand.muted }}>
                Files will land in {breadcrumbs.length ? `"${breadcrumbs[breadcrumbs.length - 1]!.name}"` : "the root folder"}
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
        title={`Move ${selectedFiles.size} file${selectedFiles.size > 1 ? "s" : ""}`}
        onClose={() => setBulkMoveOpen(false)}
        onSelect={handleBulkMove}
      />

      {/* New Folder Dialog */}
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
    </Box>
  );
}
