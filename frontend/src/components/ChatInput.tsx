import { useEffect, useState, useRef } from "react";
import {
  Box,
  Button,
  TextField,
  IconButton,
  CircularProgress,
  Chip,
  Menu,
  MenuItem,
  Tooltip,
} from "@mui/material";
import AttachFileIcon from "@mui/icons-material/AttachFile";
import CenterFocusStrongIcon from "@mui/icons-material/CenterFocusStrong";
import { uploadDocument, fetchChatModels } from "../lib/api";
import { useQuery } from "@tanstack/react-query";
import type {
  ChatFilters,
  ReasoningEffort,
  ChatMode,
  ChatModel,
  ChatScope,
} from "../lib/api";
import { useToast } from "./ToastProvider";
import { brand, fonts } from "../theme";

const MODE_LABEL: Record<ChatMode, string> = {
  plain: "Plain",
  agentic: "Agentic",
  deep: "Deep",
};

interface ChatInputProps {
  conversationId?: string | null;
  restoredSettings?: {
    model: ChatModel;
    mode: ChatMode;
    reasoning_effort?: ReasoningEffort;
  };
  onSend: (
    message: string,
    filters?: ChatFilters,
    model?: ChatModel,
    mode?: ChatMode,
    debug?: boolean,
    effort?: ReasoningEffort,
  ) => void;
  disabled: boolean;
  /** Active RAG scope for this conversation (chip + picker managed above). */
  scope?: ChatScope | null;
  onPickScope?: () => void;
  onClearScope?: () => void;
}

export default function ChatInput({
  conversationId = null,
  restoredSettings,
  onSend,
  disabled,
  scope,
  onPickScope,
  onClearScope,
}: ChatInputProps) {
  const toast = useToast();
  const catalog = useQuery({
    queryKey: ["chat-model-catalog"],
    queryFn: fetchChatModels,
    staleTime: 15 * 60_000,
    retry: false,
    throwOnError: false,
  });
  const native = catalog.data?.engine === "tsukai" && !catalog.isError;
  const rows = catalog.data?.models ?? [];
  const uniqueModels = new Map<string, (typeof rows)[number]>();
  for (const row of rows) {
    if (!uniqueModels.has(row.resolvedModel) || row.value !== "default")
      uniqueModels.set(row.resolvedModel, row);
  }
  const choices = native
    ? [...uniqueModels.values()].map((row) => ({
        id: row.resolvedModel,
        label: row.displayName,
        description: row.requires_usage_credits
          ? "Extra usage credits — unavailable"
          : row.description,
        disabled:
          Boolean(catalog.data?.stale) ||
          row.requires_usage_credits ||
          !row.selectable,
      }))
    : [
        {
          id: "sonnet",
          label: "Sonnet",
          description: "stronger reasoning",
          disabled: false,
        },
        {
          id: "haiku",
          label: "Haiku",
          description: "faster & cheaper",
          disabled: false,
        },
      ];
  const [input, setInput] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<string | null>(null);
  // New turns default to the lowest reasoning effort.
  const [mode, setMode] = useState<ChatMode>("agentic");
  const [effort, setEffort] = useState<ReasoningEffort>("low");
  const [effortAnchor, setEffortAnchor] = useState<HTMLElement | null>(null);
  const [modeAnchor, setModeAnchor] = useState<null | HTMLElement>(null);
  const [model, setModel] = useState<ChatModel>("haiku");
  const selectedModel = native
    ? (rows.find((row) => row.value === model)?.resolvedModel ?? model)
    : model;
  const selectedChoice = choices.find((choice) => choice.id === selectedModel);
  const modelEfforts = native
    ? rows.find((row) => row.resolvedModel === selectedModel)
        ?.supportedEffortLevels
    : undefined;
  const allowedEfforts = (["low", "medium", "high"] as const).filter(
    (value) => !modelEfforts || modelEfforts.includes(value),
  );
  const previousConversationId = useRef(conversationId);
  useEffect(() => {
    if (previousConversationId.current !== conversationId) {
      // Keep the chosen model when the first message creates the conversation.
      // Reset when switching conversations or starting a blank one.
      if (previousConversationId.current !== null || conversationId === null) {
        setModel("haiku");
        setMode("agentic");
        setEffort("low");
      }
      previousConversationId.current = conversationId;
    }
  }, [conversationId]);
  const restoredModel = restoredSettings?.model;
  const restoredMode = restoredSettings?.mode;
  const restoredEffort = restoredSettings?.reasoning_effort;
  useEffect(() => {
    if (restoredModel && restoredMode) {
      setModel(restoredModel);
      setMode(restoredMode === "deep" ? "agentic" : restoredMode);
      setEffort(restoredEffort ?? (restoredMode === "deep" ? "high" : "low"));
    }
  }, [restoredModel, restoredMode, restoredEffort]);
  const [modelAnchor, setModelAnchor] = useState<null | HTMLElement>(null);
  // On by default so every response gets a persisted Inspect card.
  const [debug, setDebug] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    if (!selectedChoice || selectedChoice.disabled) {
      toast.show("Choose an available model.", "error");
      return;
    }
    if (!allowedEfforts.includes(effort)) {
      toast.show(
        "Choose a supported reasoning effort for this model.",
        "error",
      );
      return;
    }
    onSend(trimmed, undefined, selectedModel, mode, debug, effort);
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
    } catch (err) {
      toast.showError(err, `Upload failed for “${file.name}”.`);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const scopeLabel = scope
    ? scope.filename
      ? `File: ${scope.filename}`
      : `Folder: ${scope.folderName}`
    : null;

  return (
    <Box
      className="chat-composer"
      sx={{
        px: { xs: 2, md: 5 },
        pb: "20px",
        display: "flex",
        flexDirection: "column",
        gap: 1,
      }}
    >
      {/* ── Scope / filter chips row ── */}
      {(uploadedFile || (scopeLabel && onPickScope)) && (
        <Box
          sx={{
            display: "flex",
            gap: 0.75,
            flexWrap: "wrap",
          }}
        >
          {scopeLabel && onPickScope && (
            <Chip
              label={`◎ ${scopeLabel}`}
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
        </Box>
      )}

      {/* Textarea followed by the options row. */}
      <Box
        className="composer-options"
        sx={{
          display: "flex",
          alignItems: "center",
          flexWrap: { xs: "wrap", md: "nowrap" },
          gap: 1,
          px: 1,
          py: 1,
          border: `1px solid ${brand.lineGlow}`,
          borderRadius: "4px",
          bgcolor: brand.surface2,
          boxShadow: "none",
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

        {/* Mode chip */}
        <Tooltip title="Mode — Plain (one-shot RAG) · Agentic (tools + iteration)">
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
        </Menu>

        <Tooltip title="Reasoning effort — Low is fastest; higher effort may help complex questions">
          <Chip
            label={`Effort: ${effort[0].toUpperCase()}${effort.slice(1)}`}
            aria-label={`Reasoning effort: ${effort}`}
            size="small"
            variant="outlined"
            disabled={disabled}
            onClick={(event) => setEffortAnchor(event.currentTarget)}
            sx={{
              fontFamily: fonts.mono,
              color: brand.purple,
              borderColor: `${brand.purple}66`,
            }}
          />
        </Tooltip>
        <Menu
          anchorEl={effortAnchor}
          open={Boolean(effortAnchor)}
          onClose={() => setEffortAnchor(null)}
        >
          {(["low", "medium", "high"] as const).map((value) => (
            <MenuItem
              key={value}
              disabled={!allowedEfforts.includes(value)}
              selected={effort === value}
              onClick={() => {
                setEffort(value);
                setEffortAnchor(null);
              }}
            >
              {value === "low"
                ? "Low — fastest (default)"
                : value === "medium"
                  ? "Medium — balanced"
                  : "High — more reasoning"}
            </MenuItem>
          ))}
        </Menu>

        {/* Model chip */}
        <Tooltip title="Model — choose the model for this response">
          <Chip
            label={selectedChoice?.label ?? "Unavailable model"}
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
          slotProps={{
            paper: { sx: { maxWidth: "min(480px, calc(100vw - 32px))" } },
          }}
        >
          {catalog.isError && (
            <MenuItem disabled>
              Model catalog unavailable — legacy choices shown
            </MenuItem>
          )}
          {catalog.isPending && (
            <MenuItem disabled>Loading model catalog…</MenuItem>
          )}
          {native && catalog.data?.stale && (
            <MenuItem disabled>Showing the last cached model catalog</MenuItem>
          )}
          {(catalog.isError || catalog.data?.stale) && (
            <MenuItem
              onClick={() => void catalog.refetch({ throwOnError: false })}
            >
              Refresh model catalog
            </MenuItem>
          )}
          {choices.map((choice) => (
            <MenuItem
              key={choice.id}
              sx={{ whiteSpace: "normal", overflowWrap: "anywhere" }}
              disabled={choice.disabled}
              selected={selectedModel === choice.id}
              onClick={() => {
                setModel(choice.id);
                setModelAnchor(null);
              }}
            >
              {choice.label}
              {choice.description ? ` — ${choice.description}` : ""}
            </MenuItem>
          ))}
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
            className="chat-debug"
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
              fontSize: "0.8125rem",
              cursor: disabled ? "default" : "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transition: "background 0.15s, border-color 0.15s",
              "&:hover:not(:disabled)": { bgcolor: `${brand.cyan}20` },
            }}
          >
            Debug
          </Box>
        </Tooltip>

        {/* Prompt prefix glyph */}
        {/* Text field */}
        <TextField
          className="composer-input"
          fullWidth
          multiline
          minRows={2}
          maxRows={6}
          placeholder="Ask a question about your documents..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          size="small"
          variant="standard"
          InputProps={{ disableUnderline: true }}
          sx={{
            minWidth: 0,
            flex: 1,
            flexBasis: { xs: "calc(100% - 52px)", md: "auto" },
            order: { xs: 1, md: 0 },
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
        <Button
          variant="contained"
          aria-label="Send"
          onClick={handleSend}
          disabled={disabled || !input.trim()}
          sx={{
            width: 40,
            order: { xs: 2, md: 0 },
            height: 34,
            flexShrink: 0,
            borderRadius: "4px",
            background:
              disabled || !input.trim() ? brand.raised : brand.magenta,
            color: brand.ink,
            fontSize: "0.9375rem",
            border: 0,
            "&:hover:not(:disabled)": {
              background: brand.magentaGlow,
              boxShadow: "none",
            },
          }}
        >
          Send
        </Button>
      </Box>
    </Box>
  );
}
