/**
 * FolderDetailPage — a single workspace for inspecting one folder.
 *
 *   /folder/:folderId
 *
 * Tabs:
 *   - Briefing (repo folders only) + the detailed architecture doc.
 *   - Documents in this folder subtree — click a card, view content in a drawer.
 *   - Mem0 memories for this folder, grouped by scope (rules / episodic).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import DescriptionIcon from "@mui/icons-material/Description";
import { Mem0BrandIcon } from "../components/BrandIcons";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import AddIcon from "@mui/icons-material/Add";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import { useNavigate, useParams } from "react-router-dom";

import BriefingPanel from "../components/BriefingPanel";
import DocumentViewerDrawer from "../components/DocumentViewerDrawer";
import { NotionSyncBanner } from "../components/NotionSyncBanner";
import DocumentationPanel from "../components/DocumentationPanel";
import FolderIntegrationsDialog from "../components/FolderIntegrationsDialog";
import { useToast } from "../components/ToastProvider";
import {
  addFolderMemory,
  deleteFolderMemory,
  fetchDocuments,
  fetchFolders,
  fetchMem0Status,
  listFolderMemories,
  type DocumentInfo,
  type Folder,
  type Mem0Status,
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

export default function FolderDetailPage() {
  const { folderId } = useParams<{ folderId: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const [folder, setFolder] = useState<Folder | null>(null);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [mem0Status, setMem0Status] = useState<Mem0Status | null>(null);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loadingMemories, setLoadingMemories] = useState(false);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [viewerFile, setViewerFile] = useState<string | null>(null);
  const [tab, setTab] = useState<"briefing" | "documents" | "memory">(
    "documents"
  );

  // Load folder metadata
  useEffect(() => {
    if (!folderId) return;
    fetchFolders(null)
      .then((roots) => {
        // Find via root then walk — but the API's fetchFolders takes parent_id.
        // Instead: search all folders — quick + correct.
        return Promise.all([
          Promise.resolve(roots),
          fetchFolders(folderId).catch(() => [] as Folder[]),
        ]);
      })
      .then(async ([roots]) => {
        const inRoot = roots.find((f) => f.id === folderId);
        if (inRoot) {
          setFolder(inRoot);
          return;
        }
        // Walk one level of each root to find sub-folders. Simple + enough
        // for the common tree shapes.
        for (const r of roots) {
          const kids = await fetchFolders(r.id).catch(() => [] as Folder[]);
          const hit = kids.find((k) => k.id === folderId);
          if (hit) {
            setFolder(hit);
            return;
          }
        }
      })
      .catch((err) => toast.showError(err, "Couldn't load folder metadata."));
  }, [folderId, toast]);

  // Repo folders default to the Briefing tab; other folders have no briefing,
  // so they open on Documents. Runs when a (new) folder loads — not on every
  // tab click — so the user's tab choice within a folder is preserved.
  useEffect(() => {
    if (!folder) return;
    setTab(folder.kind === "repo" ? "briefing" : "documents");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folder?.id, folder?.kind]);

  // Load documents
  const loadDocuments = useCallback(async () => {
    if (!folderId) return;
    setLoadingDocs(true);
    try {
      const docs = await fetchDocuments(folderId);
      setDocuments(docs);
    } catch (err) {
      toast.showError(err, "Couldn't load documents.");
    } finally {
      setLoadingDocs(false);
    }
  }, [folderId, toast]);
  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  // Load Mem0 config + memories
  const loadMem0 = useCallback(async () => {
    if (!folderId) return;
    setLoadingMemories(true);
    try {
      const status = await fetchMem0Status(folderId);
      setMem0Status(status);
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
      setLoadingMemories(false);
    }
  }, [folderId, toast]);
  useEffect(() => {
    void loadMem0();
  }, [loadMem0]);

  const openDoc = (filename: string) => {
    if (!folderId) return;
    setViewerFile(filename);
  };

  const deleteMemory = async (memory: MemoryRecord) => {
    if (!folderId) return;
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

  const [addMemoryOpen, setAddMemoryOpen] = useState(false);
  const [integrationsOpen, setIntegrationsOpen] = useState(false);

  const handleAddMemory = async (input: {
    content: string;
    category: MemoryCategory;
    scope: MemoryScope;
    tags: string[];
  }) => {
    if (!folderId) return;
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

  if (!folderId) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity="error">Missing folder id in URL.</Alert>
      </Box>
    );
  }

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        overflow: "auto",
      }}
    >
      {/* Header */}
      <Box
        sx={{
          px: 3,
          py: 2,
          borderBottom: `1px solid ${brand.line}`,
          bgcolor: alpha(brand.surface2, 0.4),
          display: "flex",
          alignItems: "center",
          gap: 1.5,
        }}
      >
        <IconButton
          onClick={() => navigate("/documents?folder=" + folderId)}
          size="small"
          sx={{ color: brand.muted }}
        >
          <ArrowBackIcon fontSize="small" />
        </IconButton>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.65rem",
              letterSpacing: "0.24em",
              color: brand.muted,
              textTransform: "uppercase",
            }}
          >
            Folder detail
          </Typography>
          <Typography
            sx={{
              fontFamily: fonts.display,
              fontSize: "1.5rem",
              fontWeight: 700,
              color: brand.text,
            }}
            noWrap
          >
            {folder?.name ?? "Loading…"}
          </Typography>
        </Box>
        <Chip
          label={`${documents.length} docs`}
          size="small"
          sx={{ fontFamily: fonts.mono, height: 22 }}
        />
        <Chip
          label={
            mem0Status?.available
              ? `${memories.length} memories`
              : "Memory: repo-only"
          }
          size="small"
          color={mem0Status?.available ? "primary" : "default"}
          sx={{ fontFamily: fonts.mono, height: 22 }}
        />
        <Button
          size="small"
          variant="outlined"
          onClick={() => setIntegrationsOpen(true)}
          sx={{ textTransform: "none", ml: 1, fontFamily: fonts.body }}
        >
          Integrations
        </Button>
      </Box>

      {/* Notion sync status for this folder's root — live progress while a
          sync runs, last-synced/error line when idle, nothing otherwise. */}
      <NotionSyncBanner key={folderId} folderId={folderId} />

      {/* Repo folders get a Briefing tab (the 8-section structured schema);
          other folders have no summary/briefing — only repos do now. */}
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{ borderBottom: `1px solid ${brand.line}`, px: 2 }}
      >
        {folder?.kind === "repo" && (
          <Tab
            value="briefing"
            label="Briefing"
            icon={<AccountTreeIcon fontSize="small" />}
            iconPosition="start"
          />
        )}
        <Tab
          value="documents"
          label={`Documents (${documents.length})`}
          icon={<DescriptionIcon fontSize="small" />}
          iconPosition="start"
        />
        <Tab
          value="memory"
          label={`Memory (${memories.length})`}
          icon={<Mem0BrandIcon fontSize="small" />}
          iconPosition="start"
        />
      </Tabs>

      <Box sx={{ p: 3, maxWidth: 960, mx: "auto", width: "100%", flex: 1 }}>
        {tab === "briefing" && folder?.kind === "repo" && (
          <>
            <BriefingPanel folderId={folderId} />
            <DocumentationPanel folderId={folderId} />
          </>
        )}

        {tab === "documents" && (
          <DocumentsSection
            documents={documents}
            loading={loadingDocs}
            onOpen={openDoc}
          />
        )}

        {tab === "memory" && (
          <MemoryTab
            available={!!mem0Status?.available}
            loading={loadingMemories}
            eternal={eternal}
            episodic={episodic}
            onDelete={deleteMemory}
            onAdd={() => setAddMemoryOpen(true)}
          />
        )}
      </Box>

      <AddMemoryDialog
        open={addMemoryOpen}
        onClose={() => setAddMemoryOpen(false)}
        onSubmit={handleAddMemory}
      />

      <FolderIntegrationsDialog
        open={integrationsOpen}
        folder={folder ? { id: folder.id, name: folder.name } : null}
        onClose={() => {
          setIntegrationsOpen(false);
          void loadMem0();
        }}
      />

      {/* Document viewer drawer */}
      <DocumentViewerDrawer
        filename={viewerFile}
        folderId={folderId}
        onClose={() => setViewerFile(null)}
      />
    </Box>
  );
}

function DocumentsSection({
  documents,
  loading,
  onOpen,
}: {
  documents: DocumentInfo[];
  loading: boolean;
  onOpen: (filename: string) => void;
}) {
  if (loading && documents.length === 0) {
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
          Loading documents…
        </Typography>
      </Box>
    );
  }
  if (documents.length === 0) {
    return (
      <Typography sx={{ fontFamily: fonts.body, color: brand.muted }}>
        No documents yet.
      </Typography>
    );
  }
  return (
    <Stack spacing={0.75}>
      {documents.map((d) => (
        <Box
          key={d.source_filename}
          onClick={() => onOpen(d.source_filename)}
          sx={{
            display: "grid",
            gridTemplateColumns: "auto 1fr auto auto",
            gap: 1.5,
            alignItems: "center",
            p: 1.5,
            border: `1px solid ${brand.line}`,
            borderLeft: `3px solid ${alpha(brand.cyan, 0.35)}`,
            borderRadius: 1.5,
            bgcolor: alpha(brand.surface, 0.5),
            cursor: "pointer",
            transition: "all 0.15s ease",
            "&:hover": {
              bgcolor: alpha(brand.violet, 0.14),
              borderColor: alpha(brand.violet, 0.55),
              borderLeftColor: brand.violet2,
              transform: "translateX(2px)",
              boxShadow: `0 4px 16px -8px ${alpha(brand.violet, 0.5)}`,
            },
          }}
        >
          <DescriptionIcon sx={{ fontSize: 18, color: brand.cyan }} />
          <Box sx={{ minWidth: 0 }}>
            <Typography
              sx={{
                fontFamily: fonts.mono,
                fontSize: "0.85rem",
                color: brand.text,
              }}
              noWrap
            >
              {d.source_filename}
            </Typography>
            <Typography
              sx={{
                fontFamily: fonts.body,
                fontSize: "0.75rem",
                color: brand.muted,
              }}
            >
              {d.source_type} · {d.chunks} chunks
            </Typography>
          </Box>
          <Chip
            label={d.status}
            size="small"
            color={d.status === "completed" ? "success" : "default"}
            sx={{ fontFamily: fonts.mono, height: 20, fontSize: "0.65rem" }}
          />
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.7rem",
              color: brand.muted,
            }}
          >
            {new Date(d.created_at).toLocaleDateString()}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}

function MemoryTab({
  available,
  loading,
  eternal,
  episodic,
  onDelete,
  onAdd,
}: {
  available: boolean;
  loading: boolean;
  eternal: MemoryRecord[];
  episodic: MemoryRecord[];
  onDelete: (m: MemoryRecord) => void;
  onAdd: () => void;
}) {
  if (!available) {
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

  return (
    <Stack spacing={3}>
      <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
        <Button
          startIcon={<AddIcon />}
          variant="outlined"
          size="small"
          onClick={onAdd}
          sx={{ fontFamily: fonts.body, textTransform: "none" }}
        >
          Add memory
        </Button>
      </Box>
      <MemoryGroup
        title="Rules"
        subtitle="Eternal preferences — always inlined at session start"
        items={eternal}
        onDelete={onDelete}
      />
      <Divider sx={{ borderColor: brand.line }} />
      <MemoryGroup
        title="Episodic"
        subtitle="Historical memories, surfaced by semantic search"
        items={episodic}
        onDelete={onDelete}
      />
    </Stack>
  );
}

function MemoryGroup({
  title,
  subtitle,
  items,
  onDelete,
}: {
  title: string;
  subtitle: string;
  items: MemoryRecord[];
  onDelete: (m: MemoryRecord) => void;
}) {
  return (
    <Box>
      <Stack
        direction="row"
        alignItems="baseline"
        spacing={1.5}
        sx={{ mb: 1.25 }}
      >
        <Typography
          sx={{
            fontFamily: fonts.display,
            fontWeight: 600,
            fontSize: "1.05rem",
            color: brand.text,
          }}
        >
          {title}
        </Typography>
        <Chip
          label={items.length}
          size="small"
          sx={{
            fontFamily: fonts.mono,
            height: 18,
            fontSize: "0.68rem",
            color: brand.muted,
            bgcolor: alpha(brand.muted, 0.1),
            border: `1px solid ${brand.line}`,
          }}
        />
        <Typography
          sx={{
            fontFamily: fonts.body,
            fontSize: "0.82rem",
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
          <MemoryCard key={m.id} m={m} onDelete={onDelete} />
        ))}
      </Stack>
    </Box>
  );
}

function MemoryCard({
  m,
  onDelete,
}: {
  m: MemoryRecord;
  onDelete: (m: MemoryRecord) => void;
}) {
  const color = CATEGORY_COLORS[m.category ?? "note"] ?? brand.muted;
  return (
    <Box
      sx={{
        p: 1.5,
        border: `1px solid ${brand.line}`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 1.5,
        bgcolor: alpha(brand.surface, 0.5),
        display: "flex",
        gap: 2,
        alignItems: "flex-start",
        transition: "all 0.15s ease",
        "&:hover": {
          borderColor: alpha(color, 0.55),
          bgcolor: alpha(color, 0.05),
          "& .mem-delete": { opacity: 1 },
        },
        "& .mem-delete": { opacity: 0.35, transition: "opacity 0.15s" },
      }}
    >
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack
          direction="row"
          spacing={0.75}
          sx={{ mb: 0.5, flexWrap: "wrap" }}
        >
          <Chip
            label={m.category ?? "?"}
            size="small"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.65rem",
              height: 20,
              bgcolor: alpha(color, 0.15),
              color,
              border: `1px solid ${alpha(color, 0.4)}`,
            }}
          />
          {m.tags.map((t) => (
            <Chip
              key={t}
              label={t}
              size="small"
              sx={{
                fontFamily: fonts.mono,
                fontSize: "0.62rem",
                height: 20,
                color: brand.muted,
                border: `1px solid ${brand.line}`,
                bgcolor: "transparent",
              }}
            />
          ))}
        </Stack>
        <Typography
          sx={{
            fontFamily: fonts.body,
            fontSize: "0.9rem",
            color: brand.text,
            lineHeight: 1.5,
          }}
        >
          {m.content}
        </Typography>
        {m.created_at && (
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.65rem",
              color: brand.muted,
              mt: 0.5,
            }}
          >
            {new Date(m.created_at).toLocaleString()}
            {m.written_by ? ` · ${m.written_by}` : ""}
          </Typography>
        )}
      </Box>
      <Tooltip title="Delete memory">
        <IconButton
          size="small"
          onClick={() => onDelete(m)}
          className="mem-delete"
          sx={{ color: brand.muted, "&:hover": { color: "#ef4444" } }}
        >
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  );
}

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
