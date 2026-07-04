import { useState, useRef, useEffect } from "react";
import {
  Box,
  TextField,
  IconButton,
  CircularProgress,
  Chip,
  Menu,
  MenuItem,
  ListSubheader,
  Tooltip,
  alpha,
} from "@mui/material";
import SendIcon from "@mui/icons-material/Send";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import FilterListIcon from "@mui/icons-material/FilterList";
import BoltIcon from "@mui/icons-material/Bolt";
import { uploadDocument, fetchDocumentFilters } from "../lib/api";
import type { ChatFilters, DocumentFilters } from "../lib/api";
import { useToast } from "./ToastProvider";

interface ChatInputProps {
  onSend: (message: string, filters?: ChatFilters, fastMode?: boolean) => void;
  disabled: boolean;
}

export default function ChatInput({ onSend, disabled }: ChatInputProps) {
  const toast = useToast();
  const [input, setInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<string | null>(null);
  const [activeFilters, setActiveFilters] = useState<ChatFilters>({});
  const [fastMode, setFastMode] = useState(false);
  const [availableFilters, setAvailableFilters] = useState<DocumentFilters>({
    topics: [],
    keywords: [],
  });
  const [filterAnchor, setFilterAnchor] = useState<null | HTMLElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Non-critical: filter dropdowns render empty on failure.
    fetchDocumentFilters()
      .then(setAvailableFilters)
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn("[ChatInput] failed to load document filters:", err);
      });
  }, []);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const filters =
      activeFilters.topic || activeFilters.keyword ? activeFilters : undefined;
    onSend(trimmed, filters, fastMode);
    setInput("");
    setUploadedFile(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      await uploadDocument(file);
      setUploadedFile(file.name);
      // Refresh filters after upload — non-critical.
      fetchDocumentFilters()
        .then(setAvailableFilters)
        .catch((err) => {
          // eslint-disable-next-line no-console
          console.warn("[ChatInput] failed to refresh filters:", err);
        });
    } catch (err) {
      toast.showError(err, `Upload failed for “${file.name}”.`);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const hasFilters = activeFilters.topic || activeFilters.keyword;
  const hasAvailableFilters =
    availableFilters.topics.length > 0 || availableFilters.keywords.length > 0;

  return (
    <Box
      sx={{
        borderTop: 1,
        borderColor: "divider",
        bgcolor: alpha("#121219", 0.5),
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
      }}
    >
      <Box sx={{ px: 2, py: 2 }}>
      <Box sx={{ display: "flex", gap: 0.5, flexWrap: "wrap", mb: uploadedFile || hasFilters ? 1 : 0 }}>
        {uploadedFile && (
          <Chip
            label={`Uploaded: ${uploadedFile}`}
            size="small"
            onDelete={() => setUploadedFile(null)}
          />
        )}
        {activeFilters.topic && (
          <Chip
            label={`Topic: ${activeFilters.topic}`}
            size="small"
            color="primary"
            onDelete={() => setActiveFilters((f) => ({ ...f, topic: undefined }))}
          />
        )}
        {activeFilters.keyword && (
          <Chip
            label={`Keyword: ${activeFilters.keyword}`}
            size="small"
            color="secondary"
            onDelete={() => setActiveFilters((f) => ({ ...f, keyword: undefined }))}
          />
        )}
      </Box>
      <Box sx={{ display: "flex", gap: 1 }}>
        <input
          type="file"
          ref={fileInputRef}
          hidden
          accept=".txt,.text,.md,.markdown,.pdf,.docx,.html,.htm,.json,.yaml,.yml"
          onChange={handleFileSelect}
        />
        <IconButton
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploading}
        >
          {uploading ? <CircularProgress size={20} /> : <AttachFileIcon />}
        </IconButton>
        <Tooltip title={hasAvailableFilters ? "Filter search" : "No filters available yet"}>
          <span>
            <IconButton
              onClick={(e) => setFilterAnchor(e.currentTarget)}
              disabled={disabled || !hasAvailableFilters}
              color={hasFilters ? "primary" : "default"}
            >
              <FilterListIcon />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={fastMode
          ? "Fast mode ON — skips query rewriting and multi-query expansion for quicker responses"
          : "Fast mode OFF — uses query rewriting and multi-query for deeper, more accurate search"
        }>
          <IconButton
            onClick={() => setFastMode((prev) => !prev)}
            disabled={disabled}
            sx={{
              color: fastMode ? "#f59e0b" : undefined,
              bgcolor: fastMode ? alpha("#f59e0b", 0.1) : undefined,
              "&:hover": {
                bgcolor: fastMode ? alpha("#f59e0b", 0.2) : undefined,
              },
            }}
          >
            <BoltIcon />
          </IconButton>
        </Tooltip>
        <Menu
          anchorEl={filterAnchor}
          open={Boolean(filterAnchor)}
          onClose={() => setFilterAnchor(null)}
        >
          {availableFilters.topics.length > 0 && (
            <ListSubheader>Topics</ListSubheader>
          )}
          {availableFilters.topics.map((t) => (
            <MenuItem
              key={`topic-${t}`}
              selected={activeFilters.topic === t}
              onClick={() => {
                setActiveFilters((f) => ({
                  ...f,
                  topic: f.topic === t ? undefined : t,
                }));
                setFilterAnchor(null);
              }}
            >
              {t}
            </MenuItem>
          ))}
          {availableFilters.keywords.length > 0 && (
            <ListSubheader>Keywords</ListSubheader>
          )}
          {availableFilters.keywords.map((k) => (
            <MenuItem
              key={`kw-${k}`}
              selected={activeFilters.keyword === k}
              onClick={() => {
                setActiveFilters((f) => ({
                  ...f,
                  keyword: f.keyword === k ? undefined : k,
                }));
                setFilterAnchor(null);
              }}
            >
              {k}
            </MenuItem>
          ))}
        </Menu>
        <TextField
          fullWidth
          multiline
          maxRows={4}
          placeholder="Ask a question about your documents..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          size="small"
        />
        <IconButton
          color="primary"
          onClick={handleSend}
          disabled={disabled || !input.trim()}
        >
          <SendIcon />
        </IconButton>
      </Box>
      </Box>
    </Box>
  );
}
