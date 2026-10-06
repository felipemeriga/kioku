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
  Typography,
} from "@mui/material";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import FilterListIcon from "@mui/icons-material/FilterList";
import CenterFocusStrongIcon from "@mui/icons-material/CenterFocusStrong";
import { uploadDocument, fetchDocumentFilters } from "../lib/api";
import type {
  ChatFilters,
  ChatMode,
  ChatModel,
  ChatScope,
  DocumentFilters,
} from "../lib/api";

const MODE_LABEL: Record<ChatMode, string> = {
  plain: "Plain",
  agentic: "Agentic",
  deep: "Deep",
};
import { useToast } from "./ToastProvider";
import { brand, fonts } from "../theme";

interface ChatInputProps {
  onSend: (
    message: string,
    filters?: ChatFilters,
    model?: ChatModel,
    mode?: ChatMode,
    debug?: boolean
  ) => void;
  disabled: boolean;
  /** Active RAG scope for this conversation (chip + picker managed above). */
  scope?: ChatScope | null;
  onPickScope?: () => void;
  onClearScope?: () => void;
}

export default function ChatInput({
  onSend,
  disabled,
  scope,
  onPickScope,
  onClearScope,
}: ChatInputProps) {
  const toast = useToast();
  const [input, setInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<string | null>(null);
  const [activeFilters, setActiveFilters] = useState<ChatFilters>({});
  // Two independent knobs (default: Sonnet + Deep).
  const [mode, setMode] = useState<ChatMode>("deep");
  const [modeAnchor, setModeAnchor] = useState<null | HTMLElement>(null);
  const [model, setModel] = useState<ChatModel>("sonnet");
  const [modelAnchor, setModelAnchor] = useState<null | HTMLElement>(null);
  // On by default so every response gets a persisted Inspect card.
  const [debug, setDebug] = useState(true);
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
        console.warn("[ChatInput] failed to load document filters:", err);
      });
  }, []);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    const filters =
      activeFilters.topic || activeFilters.keyword ? activeFilters : undefined;
    onSend(trimmed, filters, model, mode, debug);
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
  const scopeLabel = scope
    ? scope.filename
      ? `File: ${scope.filename}`
      : `Folder: ${scope.folderName}`
    : null;

  return (
    <Box
      sx={{
        px: "48px",
        pb: "20px",
        display: "flex",
        flexDirection: "column",
        gap: 1,
      }}
    >
      {/* ── Scope / filter chips row ── */}
      <Box
        sx={{
          display: "flex",
          gap: 0.75,
          flexWrap: "wrap",
        }}
      >
        {scopeLabel && (
          <Chip
            label={
              <Box
                component="span"
                sx={{ display: "flex", alignItems: "center", gap: 0.5 }}
              >
                <Typography
                  component="span"
                  sx={{ fontSize: "inherit", lineHeight: 1 }}
                >
                  ◎
                </Typography>
                {scopeLabel}
                <Typography
                  component="span"
                  sx={{
                    fontSize: "inherit",
                    lineHeight: 1,
                    color: brand.muted,
                    cursor: "pointer",
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onClearScope?.();
                  }}
                >
                  ✕
                </Typography>
              </Box>
            }
            size="small"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.75rem",
              borderRadius: "3px",
              border: `1px solid ${brand.magenta}66`,
              bgcolor: `${brand.magenta}14`,
              color: brand.magentaGlow,
              "& .MuiChip-label": { px: 1 },
            }}
            onDelete={onClearScope}
          />
        )}
        {uploadedFile && (
          <Chip
            label={`Uploaded: ${uploadedFile}`}
            size="small"
            onDelete={() => setUploadedFile(null)}
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.75rem",
              borderRadius: "3px",
            }}
          />
        )}
        {activeFilters.topic && (
          <Chip
            label={`Topic: ${activeFilters.topic}`}
            size="small"
            color="primary"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.75rem",
              borderRadius: "3px",
            }}
            onDelete={() =>
              setActiveFilters((f) => ({ ...f, topic: undefined }))
            }
          />
        )}
        {activeFilters.keyword && (
          <Chip
            label={`Keyword: ${activeFilters.keyword}`}
            size="small"
            color="secondary"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.75rem",
              borderRadius: "3px",
            }}
            onDelete={() =>
              setActiveFilters((f) => ({ ...f, keyword: undefined }))
            }
          />
        )}
      </Box>

      {/* ── Main input row ── */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          px: 1,
          py: 1,
          border: `1px solid ${brand.magenta}`,
          borderRadius: "4px",
          bgcolor: brand.surface2,
          boxShadow: `0 0 12px ${brand.magenta}44`,
        }}
      >
        <input
          type="file"
          ref={fileInputRef}
          hidden
          accept=".txt,.text,.md,.markdown,.pdf,.docx,.html,.htm,.json,.yaml,.yml"
          onChange={handleFileSelect}
        />

        {/* Attach */}
        <IconButton
          aria-label="Attach file"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploading}
          sx={{ width: 34, height: 34, color: brand.muted, flexShrink: 0 }}
        >
          {uploading ? (
            <CircularProgress size={18} />
          ) : (
            <AttachFileIcon sx={{ fontSize: 18 }} />
          )}
        </IconButton>

        {/* Scope picker */}
        {onPickScope && (
          <Tooltip
            title={
              scope
                ? "Change the folder/file this chat searches"
                : "Limit this chat to one folder or file"
            }
          >
            <IconButton
              aria-label="Scope"
              onClick={onPickScope}
              disabled={disabled}
              sx={{
                width: 34,
                height: 34,
                flexShrink: 0,
                color: scope ? brand.magenta : brand.muted,
                bgcolor: scope ? `${brand.magenta}22` : "transparent",
                "&:hover": { bgcolor: `${brand.magenta}22` },
              }}
            >
              <CenterFocusStrongIcon sx={{ fontSize: 18 }} />
            </IconButton>
          </Tooltip>
        )}

        {/* Filter */}
        <Tooltip
          title={
            hasAvailableFilters ? "Filter search" : "No filters available yet"
          }
        >
          <span>
            <IconButton
              aria-label="Filters"
              onClick={(e) => setFilterAnchor(e.currentTarget)}
              disabled={disabled || !hasAvailableFilters}
              sx={{
                width: 34,
                height: 34,
                flexShrink: 0,
                color: hasFilters ? brand.magenta : brand.muted,
              }}
            >
              <FilterListIcon sx={{ fontSize: 18 }} />
            </IconButton>
          </span>
        </Tooltip>

        {/* Mode chip */}
        <Tooltip title="Mode — Plain (one-shot RAG) · Agentic (tools + loop) · Deep (+ reasoning)">
          <Chip
            label={MODE_LABEL[mode]}
            size="small"
            variant="outlined"
            disabled={disabled}
            onClick={(e) => setModeAnchor(e.currentTarget)}
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.75rem",
              borderRadius: "3px",
              cursor: "pointer",
              flexShrink: 0,
              color: brand.purple,
              borderColor: `${brand.purple}66`,
              bgcolor: `${brand.purple}22`,
              "& .MuiChip-label": { px: 1 },
            }}
          />
        </Tooltip>
        <Menu
          anchorEl={modeAnchor}
          open={Boolean(modeAnchor)}
          onClose={() => setModeAnchor(null)}
        >
          <MenuItem
            selected={mode === "plain"}
            onClick={() => {
              setMode("plain");
              setModeAnchor(null);
            }}
          >
            Plain — classic one-shot RAG
          </MenuItem>
          <MenuItem
            selected={mode === "agentic"}
            onClick={() => {
              setMode("agentic");
              setModeAnchor(null);
            }}
          >
            Agentic — tools + iteration
          </MenuItem>
          <MenuItem
            selected={mode === "deep"}
            onClick={() => {
              setMode("deep");
              setModeAnchor(null);
            }}
          >
            Deep — agentic + reasoning
          </MenuItem>
        </Menu>

        {/* Model chip */}
        <Tooltip title="Model — pick Sonnet (stronger) or Haiku (faster/cheaper)">
          <Chip
            label={model === "sonnet" ? "Sonnet" : "Haiku"}
            size="small"
            variant="outlined"
            disabled={disabled}
            onClick={(e) => setModelAnchor(e.currentTarget)}
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.75rem",
              borderRadius: "3px",
              cursor: "pointer",
              flexShrink: 0,
              borderColor: brand.lineGlow,
              "& .MuiChip-label": { px: 1 },
            }}
          />
        </Tooltip>
        <Menu
          anchorEl={modelAnchor}
          open={Boolean(modelAnchor)}
          onClose={() => setModelAnchor(null)}
        >
          <MenuItem
            selected={model === "sonnet"}
            onClick={() => {
              setModel("sonnet");
              setModelAnchor(null);
            }}
          >
            Sonnet — stronger reasoning
          </MenuItem>
          <MenuItem
            selected={model === "haiku"}
            onClick={() => {
              setModel("haiku");
              setModelAnchor(null);
            }}
          >
            Haiku — faster & cheaper
          </MenuItem>
        </Menu>

        {/* DBG toggle */}
        <Tooltip
          title={
            debug
              ? "Debug ON — each answer gets an Inspect card (chunks, rerank, reasoning, tool calls)"
              : "Debug OFF — turn on to inspect how each answer was produced"
          }
        >
          <Box
            component="button"
            aria-label="Debug"
            onClick={() => setDebug((prev) => !prev)}
            disabled={disabled}
            sx={{
              width: 34,
              height: 34,
              flexShrink: 0,
              border: debug
                ? `1px solid ${brand.cyan}55`
                : `1px solid ${brand.line}`,
              borderRadius: "3px",
              background: debug ? `${brand.cyan}14` : "transparent",
              color: debug ? brand.cyan : brand.muted,
              fontFamily: fonts.mono,
              fontSize: "0.6875rem",
              cursor: disabled ? "default" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "background 0.15s, border-color 0.15s",
              "&:hover:not(:disabled)": { bgcolor: `${brand.cyan}20` },
            }}
          >
            DBG
          </Box>
        </Tooltip>

        {/* Prompt prefix glyph */}
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: "0.875rem",
            color: brand.magenta,
            ml: 0.75,
            flexShrink: 0,
            userSelect: "none",
          }}
        >
          &gt;
        </Typography>

        {/* Text field */}
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
          variant="standard"
          InputProps={{ disableUnderline: true }}
          sx={{
            "& .MuiInputBase-root": {
              bgcolor: "transparent",
              borderRadius: 0,
              px: 0,
            },
            "& .MuiInputBase-input": {
              color: brand.text,
              fontFamily: fonts.body,
              fontSize: "0.875rem",
            },
            "& .MuiInputBase-input::placeholder": {
              color: brand.dim,
              opacity: 1,
            },
          }}
        />

        {/* Neon send button */}
        <IconButton
          aria-label="Send"
          onClick={handleSend}
          disabled={disabled || !input.trim()}
          sx={{
            width: 40,
            height: 34,
            flexShrink: 0,
            borderRadius: "4px",
            background:
              disabled || !input.trim()
                ? `${brand.magenta}44`
                : `linear-gradient(90deg, ${brand.magentaDeep} 0%, ${brand.purple} 100%)`,
            color: "#fff",
            fontSize: "0.9375rem",
            border: 0,
            "&:hover:not(:disabled)": {
              background: `linear-gradient(90deg, ${brand.magenta} 0%, ${brand.purple} 100%)`,
              boxShadow: `0 0 16px ${brand.magenta}55`,
            },
          }}
        >
          ➤
        </IconButton>
      </Box>

      {/* Filter menus (kept out of toolbar to preserve DOM structure) */}
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
    </Box>
  );
}
