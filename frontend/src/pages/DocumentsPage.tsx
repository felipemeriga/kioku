import { useRef, useState, useCallback, useEffect } from "react";
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
} from "@mui/material";
import { useSearchParams } from "react-router-dom";
import { keyframes } from "@mui/system";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import DeleteIcon from "@mui/icons-material/Delete";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import FolderIcon from "@mui/icons-material/Folder";
import MicIcon from "@mui/icons-material/Mic";
import DriveFileMoveIcon from "@mui/icons-material/DriveFileMove";
import CloseIcon from "@mui/icons-material/Close";
import StopIcon from "@mui/icons-material/Stop";
import { useDocuments } from "../hooks/useDocuments";
import { useIngestionStatus } from "../hooks/useIngestionStatus";
import {
  createFolder,
  fetchFolders,
  deleteFolder,
  downloadDocument,
} from "../lib/api";
import DocumentCard from "../components/DocumentCard";
import MoveDialog from "../components/MoveDialog";
import IngestionDrawer from "../components/IngestionDrawer";

const ACCEPTED_TYPES =
  ".txt,.text,.md,.markdown,.pdf,.docx,.html,.htm,.json,.yaml,.yml,.png,.jpg,.jpeg,.mp3,.webm,.m4a";

const pulse = keyframes`
  0% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.15); }
  100% { opacity: 1; transform: scale(1); }
`;
export default function DocumentsPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

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
        upload(file, currentFolderId);
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        mediaRecorderRef.current = null;
      };
      recorder.start();
      setRecordingTime(0);
      setIsRecording(true);
    } catch {
      alert("Microphone access denied. Please allow microphone permissions.");
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

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    for (const file of Array.from(files)) {
      upload(file, currentFolderId);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      for (const file of files) {
        upload(file, currentFolderId);
      }
    },
    [upload, currentFolderId]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const [subFolders, setSubFolders] = useState<{ id: string; name: string }[]>(
    []
  );

  // Load subfolders of current directory for the grid view
  const loadSubFolders = useCallback(() => {
    fetchFolders(currentFolderId)
      .then((data) =>
        setSubFolders(data.map((f) => ({ id: f.id, name: f.name })))
      )
      .catch(() => {});
  }, [currentFolderId]);

  useEffect(() => {
    loadSubFolders();
  }, [loadSubFolders]);

  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) return;
    await createFolder(newFolderName.trim(), currentFolderId);
    setNewFolderName("");
    setNewFolderOpen(false);
    loadSubFolders();
    // Notify sidebar FolderTree to refresh
    window.dispatchEvent(new CustomEvent("folders-changed"));
  };

  const handleRequestDeleteFolder = useCallback(
    (folderId: string, folderName: string) => {
      setDeleteConfirm({ type: "folder", id: folderId, name: folderName });
    },
    [setDeleteConfirm]
  );

  const handleConfirmDelete = async () => {
    if (!deleteConfirm) return;
    if (deleteConfirm.type === "folder") {
      await deleteFolder(deleteConfirm.id);
      if (currentFolderId === deleteConfirm.id) {
        setCurrentFolderId(null);
      }
      loadSubFolders();
    } else if (deleteConfirm.id.includes(",")) {
      // Bulk delete — id is comma-separated filenames
      const filenames = deleteConfirm.id.split(",");
      for (const filename of filenames) {
        await remove(filename);
      }
      clearSelection();
    } else {
      await remove(deleteConfirm.name);
    }
    setDeleteConfirm(null);
  };

  const handleDownload = async (filename: string) => {
    try {
      const url = await downloadDocument(filename);
      window.open(url, "_blank");
    } catch {
      // Silently fail — button is only shown when has_file is true
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
            py: 1.5,
            display: "flex",
            alignItems: "center",
            gap: 2,
            borderBottom: 1,
            borderColor: "divider",
            bgcolor: alpha("#121219", 0.4),
          }}
        >
          <Box sx={{ flex: 1 }}>
            <Typography
              sx={{
                fontFamily: '"Space Grotesk", sans-serif',
                fontWeight: 700,
                fontSize: "1.15rem",
                letterSpacing: "-0.02em",
                lineHeight: 1.1,
              }}
            >
              {currentFolderId ? "Folder Contents" : "All Documents"}
            </Typography>
            <Typography
              sx={{
                fontFamily: '"JetBrains Mono", monospace',
                fontSize: "0.62rem",
                letterSpacing: "0.24em",
                color: "text.secondary",
                mt: 0.25,
              }}
            >
              INGESTED CORPUS
            </Typography>
          </Box>
          {ingestionTasks.length > 0 && (
            <Tooltip title="Processing status">
              <IconButton size="small" onClick={openIngestionDrawer}>
                <Badge
                  badgeContent={
                    ingestionTasks.filter(
                      (t) =>
                        !["completed", "error", "duplicate"].includes(t.stage)
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
            variant="contained"
            size="small"
            startIcon={<UploadFileIcon />}
            onClick={() => fileInputRef.current?.click()}
          >
            Upload
          </Button>
        </Box>

        {/* Content area */}
        <Box sx={{ flex: 1, overflow: "auto", p: 3 }}>
          {/* Drop zone */}
          <Box
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            sx={{
              border: 2,
              borderStyle: "dashed",
              borderColor: dragOver ? "primary.main" : alpha("#ffffff", 0.08),
              borderRadius: 3,
              p: 2.5,
              mb: 3,
              textAlign: "center",
              bgcolor: dragOver
                ? alpha("#7c3aed", 0.08)
                : alpha("#1e1e2e", 0.2),
              transition: "all 0.2s ease-in-out",
              cursor: "pointer",
              "&:hover": {
                borderColor: alpha("#7c3aed", 0.3),
                bgcolor: alpha("#7c3aed", 0.04),
              },
            }}
            onClick={() => fileInputRef.current?.click()}
          >
            <CloudUploadIcon
              sx={{ fontSize: 32, color: alpha("#7c3aed", 0.4), mb: 0.5 }}
            />
            <Typography color="text.secondary" variant="body2">
              Drop files here or click to browse
            </Typography>
            <Typography variant="caption" sx={{ color: alpha("#ffffff", 0.3) }}>
              PDF, DOCX, HTML, Markdown, text, JSON, YAML, PNG, JPEG, or audio
            </Typography>
            <Box
              sx={{
                mt: 1.5,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 1,
              }}
            >
              <IconButton
                onClick={handleMicClick}
                sx={{
                  bgcolor: isRecording
                    ? alpha("#ef4444", 0.2)
                    : alpha("#7c3aed", 0.1),
                  border: `1px solid ${
                    isRecording ? alpha("#ef4444", 0.5) : alpha("#7c3aed", 0.25)
                  }`,
                  color: isRecording ? "#ef4444" : alpha("#7c3aed", 0.7),
                  "&:hover": {
                    bgcolor: isRecording
                      ? alpha("#ef4444", 0.3)
                      : alpha("#7c3aed", 0.2),
                  },
                }}
              >
                {isRecording ? (
                  <StopIcon fontSize="small" />
                ) : (
                  <MicIcon fontSize="small" />
                )}
              </IconButton>
              {isRecording && (
                <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
                  <Box
                    sx={{
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      bgcolor: "#ef4444",
                      animation: `${pulse} 1.2s ease-in-out infinite`,
                    }}
                  />
                  <Typography
                    variant="caption"
                    sx={{ color: "#ef4444", fontFamily: "monospace" }}
                  >
                    {formatTime(recordingTime)}
                  </Typography>
                </Box>
              )}
            </Box>
          </Box>

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {/* Sub-folders grid */}
          {subFolders.length > 0 && (
            <Box sx={{ mb: 3 }}>
              <Typography
                variant="caption"
                sx={{
                  color: alpha("#ffffff", 0.35),
                  mb: 1,
                  display: "block",
                  letterSpacing: 1.5,
                  textTransform: "uppercase",
                  fontSize: "0.65rem",
                }}
              >
                Folders
              </Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
                  gap: 1.5,
                }}
              >
                {subFolders.map((folder) => (
                  <Paper
                    key={folder.id}
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
                          ? alpha("#7c3aed", 0.12)
                          : alpha("#1e1e2e", 0.4),
                      border: `1px solid ${
                        dragOverFolderId === folder.id
                          ? alpha("#7c3aed", 0.5)
                          : alpha("#ffffff", 0.04)
                      }`,
                      transition: "all 0.15s ease",
                      "&:hover": {
                        transform: "translateY(-1px)",
                        borderColor: alpha("#7c3aed", 0.25),
                        boxShadow: `0 4px 16px ${alpha("#7c3aed", 0.1)}`,
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
                    <FolderIcon sx={{ fontSize: 36, color: "#7c3aed" }} />
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
          {documents.length > 0 && (
            <Box>
              <Typography
                variant="caption"
                sx={{
                  color: alpha("#ffffff", 0.35),
                  mb: 1,
                  display: "block",
                  letterSpacing: 1.5,
                  textTransform: "uppercase",
                  fontSize: "0.65rem",
                }}
              >
                Files
              </Typography>
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
                  gap: 1.5,
                }}
              >
                {documents.map((doc) => (
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

          {/* Empty state */}
          {isEmpty && (
            <Box sx={{ textAlign: "center", mt: 8 }}>
              <FolderIcon
                sx={{ fontSize: 56, color: alpha("#ffffff", 0.08), mb: 1.5 }}
              />
              <Typography variant="body2" sx={{ color: alpha("#ffffff", 0.3) }}>
                {currentFolderId
                  ? "This folder is empty"
                  : "No documents yet. Upload files to get started."}
              </Typography>
            </Box>
          )}
        </Box>

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
            borderColor: alpha("#7c3aed", 0.3),
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
    </Box>
  );
}
