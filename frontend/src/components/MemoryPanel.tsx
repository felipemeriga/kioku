/**
 * MemoryPanel — self-contained Mem0 memory browser for a folder.
 *
 * Owns all memory state: loading, add, delete, Rules/Episodic grouping.
 * Drop it anywhere a folderId is available (FolderDetailPage, DocumentsPage).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import CornerCard from "./neo/CornerCard";
import { useToast } from "./ToastProvider";
import {
  addFolderMemory,
  deleteFolderMemory,
  fetchMem0Status,
  listFolderMemories,
  type MemoryCategory,
  type MemoryRecord,
  type MemoryScope,
} from "../lib/api";
import { brand, fonts } from "../theme";

const CATEGORY_COLORS: Record<string, string> = {
  decision: brand.violet2,
  finding: brand.cyan,
  issue: brand.amber,
  preference: brand.green,
  session: brand.muted,
  note: brand.muted,
};

const CATEGORY_OPTIONS: {
  value: MemoryCategory;
  label: string;
  hint: string;
}[] = [
  {
    value: "decision",
    label: "Decision",
    hint: "an architectural / design choice",
  },
  {
    value: "finding",
    label: "Finding",
    hint: "an empirical fact you discovered",
  },
  { value: "issue", label: "Issue", hint: "a bug, limitation, or workaround" },
  {
    value: "preference",
    label: "Preference",
    hint: "how you like to work (usually eternal)",
  },
  { value: "session", label: "Session", hint: "summary of a working session" },
  {
    value: "note",
    label: "Note",
    hint: "freeform — prefer a more specific category",
  },
];

export default function MemoryPanel({ folderId }: { folderId: string }) {
  const toast = useToast();

  const [available, setAvailable] = useState(false);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [addMemoryOpen, setAddMemoryOpen] = useState(false);

  const loadMem0 = useCallback(async () => {
    setLoading(true);
    try {
      const status = await fetchMem0Status(folderId);
      setAvailable(!!status.available);
      if (status.available) {
        const res = await listFolderMemories(folderId, {
          scope: "any",
          limit: 200,
        });
        setMemories(res.memories);
      } else {
        setMemories([]);
      }
    } catch (err) {
      toast.showError(err, "Couldn't load memories.");
    } finally {
      setLoading(false);
    }
  }, [folderId, toast]);

  useEffect(() => {
    void loadMem0();
  }, [loadMem0]);

  const deleteMemory = async (memory: MemoryRecord) => {
    if (!confirm(`Delete this memory?\n\n${memory.content.slice(0, 120)}…`))
      return;
    try {
      await deleteFolderMemory(folderId, memory.id);
      setMemories((prev) => prev.filter((m) => m.id !== memory.id));
      toast.showSuccess("Memory deleted.");
    } catch (err) {
      toast.showError(err, "Couldn't delete memory.");
    }
  };

  const eternal = useMemo(
    () => memories.filter((m) => m.scope === "eternal"),
    [memories]
  );
  const episodic = useMemo(
    () => memories.filter((m) => m.scope !== "eternal"),
    [memories]
  );

  const handleAddMemory = async (input: {
    content: string;
    category: MemoryCategory;
    scope: MemoryScope;
    tags: string[];
  }) => {
    try {
      const res = await addFolderMemory({
        root_folder_id: folderId,
        ...input,
        written_by: "user",
      });
      setAddMemoryOpen(false);
      if (res.duplicate) {
        toast.show("Memory already exists — merged tags into it.", "info");
      } else {
        toast.showSuccess("Memory added.");
      }
      await loadMem0();
    } catch (err) {
      toast.showError(err, "Couldn't save memory.");
    }
  };

  // Show the spinner first while status resolves, so the "not available"
  // alert never flashes before loadMem0() has actually confirmed the folder
  // isn't a repo.
  if (loading && eternal.length === 0 && episodic.length === 0) {
    return (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          color: brand.muted,
        }}
      >
        <CircularProgress size={16} sx={{ color: brand.violet2 }} />
        <Typography sx={{ fontFamily: fonts.body, fontSize: "0.9rem" }}>
          Loading memories…
        </Typography>
      </Box>
    );
  }

  if (!loading && !available) {
    return (
      <Box>
        <Alert severity="info" sx={{ mb: 2 }}>
          Memory is available on repo folders. Run <code>kioku init</code> in
          this folder to make it a repo — then episodic + eternal memory is on
          automatically, no connection needed.
        </Alert>
      </Box>
    );
  }

  return (
    <>
      <Stack spacing={2}>
        {/* + Add memory — purple outlined, board spec */}
        <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
          <Button
            startIcon={<AddIcon />}
            variant="outlined"
            size="small"
            onClick={() => setAddMemoryOpen(true)}
            sx={{
              height: 36,
              textTransform: "none",
              borderColor: brand.purple,
              bgcolor: `${brand.purple}1a`,
              color: "#E2B8FF",
              fontFamily: fonts.body,
              fontWeight: 600,
              fontSize: 13,
              boxShadow: `0 0 12px ${brand.purple}33`,
              "&:hover": {
                borderColor: brand.purple,
                bgcolor: `${brand.purple}2a`,
              },
            }}
          >
            Add memory
          </Button>
        </Box>

        {/* Rules group */}
        <MemoryGroup
          title="Rules"
          subtitle="Eternal preferences — always inlined at session start"
          variant="rules"
          items={eternal}
          onDelete={deleteMemory}
        />

        {/* Gradient divider */}
        <Box
          sx={{
            height: 1,
            backgroundImage: `linear-gradient(90deg, transparent, ${brand.purple}, transparent)`,
            my: 0.75,
          }}
        />

        {/* Episodic group */}
        <MemoryGroup
          title="Episodic"
          subtitle="Historical memories, surfaced by semantic search"
          variant="episodic"
          items={episodic}
          onDelete={deleteMemory}
        />
      </Stack>

      <AddMemoryDialog
        open={addMemoryOpen}
        onClose={() => setAddMemoryOpen(false)}
        onSubmit={handleAddMemory}
      />
    </>
  );
}

function MemoryGroup({
  title,
  subtitle,
  variant,
  items,
  onDelete,
}: {
  title: string;
  subtitle: string;
  variant: "rules" | "episodic";
  items: MemoryRecord[];
  onDelete: (m: MemoryRecord) => void;
}) {
  const isRules = variant === "rules";
  const badgeBorder = isRules ? `${brand.amber}66` : `${brand.purple}66`;
  const badgeColor = isRules ? brand.amber : "#E2B8FF";

  return (
    <Box
      sx={
        isRules
          ? {
              border: `1px solid ${brand.amber}55`,
              bgcolor: `${brand.amber}08`,
              borderRadius: 1,
              p: 2,
            }
          : { p: 0 }
      }
    >
      {/* Section header: title + count badge + italic description */}
      <Stack
        direction="row"
        alignItems="baseline"
        spacing={1.25}
        sx={{ mb: 1.5 }}
      >
        <Typography
          sx={{
            fontFamily: fonts.display,
            fontWeight: 600,
            fontSize: 18,
            color: brand.text,
          }}
        >
          {title}
        </Typography>
        <Box
          component="span"
          sx={{
            px: "7px",
            py: "1px",
            border: `1px solid ${badgeBorder}`,
            borderRadius: "3px",
            color: badgeColor,
            fontFamily: fonts.mono,
            fontSize: 11,
            lineHeight: 1.6,
          }}
        >
          {items.length}
        </Box>
        <Typography
          sx={{
            fontFamily: fonts.body,
            fontSize: 13,
            color: brand.muted,
            fontStyle: "italic",
          }}
        >
          {subtitle}
        </Typography>
      </Stack>

      {items.length === 0 && (
        <Typography
          sx={{
            fontFamily: fonts.body,
            fontSize: "0.85rem",
            color: brand.muted,
          }}
        >
          None yet.
        </Typography>
      )}
      <Stack spacing={1}>
        {items.map((m) => (
          <MemoryCard key={m.id} m={m} variant={variant} onDelete={onDelete} />
        ))}
      </Stack>
    </Box>
  );
}

function MemoryCard({
  m,
  variant,
  onDelete,
}: {
  m: MemoryRecord;
  variant: "rules" | "episodic";
  onDelete: (m: MemoryRecord) => void;
}) {
  const color = CATEGORY_COLORS[m.category ?? "note"] ?? brand.muted;
  const isRules = variant === "rules";

  return (
    <CornerCard
      color={isRules ? brand.amber : brand.line}
      corners={isRules ? 4 : 2}
      sx={{
        p: "14px 16px",
        bgcolor: isRules ? "transparent" : brand.surface,
        border: isRules
          ? `1px solid ${brand.amber}55`
          : `1px solid ${brand.line}`,
        boxShadow: `inset 2px 0 0 ${color}`,
        display: "flex",
        gap: 1.5,
        alignItems: "flex-start",
        transition: "all 0.15s ease",
        "&:hover": {
          borderColor: isRules ? `${brand.amber}88` : alpha(color, 0.45),
          bgcolor: isRules ? `${brand.amber}10` : alpha(color, 0.04),
          "& .mem-delete": { opacity: 1 },
        },
        "& .mem-delete": { opacity: 0.35, transition: "opacity 0.15s" },
      }}
    >
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: "6px",
        }}
      >
        {/* Category badge + tag chips */}
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap" }}>
          <Box
            component="span"
            sx={{
              px: "8px",
              py: "2px",
              borderRadius: "3px",
              bgcolor: `${color}22`,
              border: `1px solid ${color}88`,
              color,
              fontFamily: fonts.mono,
              fontSize: 11,
              lineHeight: 1.6,
            }}
          >
            {m.category ?? "?"}
          </Box>
          {m.tags.map((t) => (
            <Box
              key={t}
              component="span"
              sx={{
                px: "8px",
                py: "2px",
                borderRadius: "3px",
                border: `1px solid ${brand.lineGlow}`,
                color: brand.muted,
                fontFamily: fonts.mono,
                fontSize: 11,
                lineHeight: 1.6,
              }}
            >
              {t}
            </Box>
          ))}
        </Stack>

        {/* Memory text */}
        <Typography
          sx={{
            fontFamily: fonts.body,
            fontSize: 15,
            color: brand.text,
            lineHeight: 1.5,
          }}
        >
          {m.content}
        </Typography>

        {/* Timestamp · author */}
        {m.created_at && (
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: 11,
              color: brand.muted,
            }}
          >
            {new Date(m.created_at).toLocaleString()}
            {m.written_by ? ` · ${m.written_by}` : ""}
          </Typography>
        )}
      </Box>

      {/* Delete button */}
      <Tooltip title="Delete memory">
        <IconButton
          size="small"
          onClick={() => onDelete(m)}
          className="mem-delete"
          sx={{
            width: 30,
            height: 30,
            border: 0,
            borderRadius: "3px",
            color: brand.muted,
            "&:hover": { color: brand.red, bgcolor: `${brand.red}12` },
          }}
        >
          <DeleteIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Tooltip>
    </CornerCard>
  );
}

function AddMemoryDialog({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (input: {
    content: string;
    category: MemoryCategory;
    scope: MemoryScope;
    tags: string[];
  }) => void | Promise<void>;
}) {
  const [content, setContent] = useState("");
  const [category, setCategory] = useState<MemoryCategory>("decision");
  const [scope, setScope] = useState<MemoryScope>("episodic");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setContent("");
    setCategory("decision");
    setScope("episodic");
    setTags("");
  };

  const handleSubmit = async () => {
    setBusy(true);
    try {
      await onSubmit({
        content: content.trim(),
        category,
        scope,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
      reset();
    } finally {
      setBusy(false);
    }
  };

  const currentHint = CATEGORY_OPTIONS.find((c) => c.value === category)?.hint;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="sm"
      PaperProps={{
        sx: { bgcolor: brand.surface, border: `1px solid ${brand.line}` },
      }}
    >
      <DialogTitle sx={{ fontFamily: fonts.display }}>Add memory</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Memory"
            multiline
            minRows={3}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="e.g. Backend uses uv (not pip) — run `uv add <pkg>` and `uv run <cmd>`."
            fullWidth
            autoFocus
          />
          <Stack direction="row" spacing={2}>
            <FormControl fullWidth>
              <InputLabel>Category</InputLabel>
              <Select
                value={category}
                label="Category"
                onChange={(e) => setCategory(e.target.value as MemoryCategory)}
              >
                {CATEGORY_OPTIONS.map((c) => (
                  <MenuItem key={c.value} value={c.value}>
                    {c.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl fullWidth>
              <InputLabel>Scope</InputLabel>
              <Select
                value={scope}
                label="Scope"
                onChange={(e) => setScope(e.target.value as MemoryScope)}
              >
                <MenuItem value="episodic">Episodic (history)</MenuItem>
                <MenuItem value="eternal">Eternal (always applies)</MenuItem>
              </Select>
            </FormControl>
          </Stack>
          {currentHint && (
            <Typography
              sx={{
                fontFamily: fonts.body,
                fontSize: "0.78rem",
                color: brand.muted,
                fontStyle: "italic",
              }}
            >
              {currentHint}
            </Typography>
          )}
          <TextField
            label="Tags (comma-separated)"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="e.g. auth, security"
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions sx={{ pr: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={!content.trim() || busy}
        >
          {busy ? "Saving…" : "Save memory"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
