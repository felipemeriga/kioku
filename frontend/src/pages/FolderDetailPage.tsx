/**
 * FolderDetailPage — a single workspace for inspecting one folder.
 *
 *   /folder/:folderId
 *
 * Three stacked sections:
 *   1) Folder orientation (the composed summary panel, full width).
 *   2) Documents in this folder subtree — click a card, view content in a drawer.
 *   3) Mem0 memories for this folder, grouped by scope (rules / episodic).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Divider,
  Drawer,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import DeleteIcon from "@mui/icons-material/Delete";
import DescriptionIcon from "@mui/icons-material/Description";
import PsychologyIcon from "@mui/icons-material/Psychology";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import { useNavigate, useParams } from "react-router-dom";

import FolderSummaryPanel from "../components/FolderSummaryPanel";
import { useToast, messageFromError } from "../components/ToastProvider";
import {
  deleteFolderMemory,
  fetchDocumentContent,
  fetchDocuments,
  fetchFolders,
  fetchMem0Configs,
  listFolderMemories,
  type DocumentContent,
  type DocumentInfo,
  type Folder,
  type Mem0Config,
  type MemoryRecord,
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
  const [mem0Config, setMem0Config] = useState<Mem0Config | null>(null);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loadingMemories, setLoadingMemories] = useState(false);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [selectedDoc, setSelectedDoc] = useState<DocumentContent | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [tab, setTab] = useState<"summary" | "documents" | "memory">("summary");

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
      const configs = await fetchMem0Configs();
      const cfg = configs.find((c) => c.root_folder_id === folderId) ?? null;
      setMem0Config(cfg);
      if (cfg) {
        const res = await listFolderMemories(cfg.id, { scope: "any", limit: 200 });
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

  const openDoc = async (filename: string) => {
    if (!folderId) return;
    setLoadingDoc(true);
    setSelectedDoc({
      source_filename: filename,
      source_type: null,
      metadata: {},
      chunk_count: 0,
      folder_id: folderId,
      status: null,
      created_at: null,
      content: "",
    });
    try {
      const doc = await fetchDocumentContent(filename, folderId);
      setSelectedDoc(doc);
    } catch (err) {
      toast.showError(err, "Couldn't load document content.");
      setSelectedDoc(null);
    } finally {
      setLoadingDoc(false);
    }
  };

  const deleteMemory = async (memory: MemoryRecord) => {
    if (!mem0Config) return;
    if (!confirm(`Delete this memory?\n\n${memory.content.slice(0, 120)}…`))
      return;
    try {
      await deleteFolderMemory(mem0Config.id, memory.id);
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
          label={mem0Config ? `${memories.length} memories` : "Mem0 not connected"}
          size="small"
          color={mem0Config ? "primary" : "default"}
          sx={{ fontFamily: fonts.mono, height: 22 }}
        />
      </Box>

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{ borderBottom: `1px solid ${brand.line}`, px: 2 }}
      >
        <Tab value="summary" label="Summary" icon={<AutoAwesomeIcon fontSize="small" />} iconPosition="start" />
        <Tab value="documents" label={`Documents (${documents.length})`} icon={<DescriptionIcon fontSize="small" />} iconPosition="start" />
        <Tab value="memory" label={`Memory (${memories.length})`} icon={<PsychologyIcon fontSize="small" />} iconPosition="start" />
      </Tabs>

      <Box sx={{ p: 3, maxWidth: 960, mx: "auto", width: "100%", flex: 1 }}>
        {tab === "summary" && (
          <FolderSummaryPanel
            folderId={folderId}
            folderName={folder?.name ?? "this folder"}
          />
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
            connected={!!mem0Config}
            loading={loadingMemories}
            eternal={eternal}
            episodic={episodic}
            onDelete={deleteMemory}
          />
        )}
      </Box>

      {/* Document viewer drawer */}
      <Drawer
        anchor="right"
        open={!!selectedDoc}
        onClose={() => setSelectedDoc(null)}
        PaperProps={{
          sx: {
            width: { xs: "100%", sm: 640 },
            bgcolor: brand.ink,
            borderLeft: `1px solid ${brand.line}`,
          },
        }}
      >
        <DocumentDrawerBody
          doc={selectedDoc}
          loading={loadingDoc}
          onClose={() => setSelectedDoc(null)}
        />
      </Drawer>
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
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, color: brand.muted }}>
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
            borderRadius: 1.5,
            bgcolor: alpha(brand.surface, 0.5),
            cursor: "pointer",
            transition: "background 0.15s, border-color 0.15s",
            "&:hover": {
              bgcolor: alpha(brand.violet, 0.06),
              borderColor: alpha(brand.violet, 0.4),
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
            sx={{ fontFamily: fonts.mono, fontSize: "0.7rem", color: brand.muted }}
          >
            {new Date(d.created_at).toLocaleDateString()}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}

function MemoryTab({
  connected,
  loading,
  eternal,
  episodic,
  onDelete,
}: {
  connected: boolean;
  loading: boolean;
  eternal: MemoryRecord[];
  episodic: MemoryRecord[];
  onDelete: (m: MemoryRecord) => void;
}) {
  if (!connected) {
    return (
      <Alert severity="info">
        No Mem0 integration connected for this folder. Right-click the folder
        in the sidebar → Manage integrations → Connect Mem0.
      </Alert>
    );
  }
  if (loading && eternal.length === 0 && episodic.length === 0) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, color: brand.muted }}>
        <CircularProgress size={16} sx={{ color: brand.violet2 }} />
        <Typography sx={{ fontFamily: fonts.body, fontSize: "0.9rem" }}>
          Loading memories…
        </Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={3}>
      <MemoryGroup
        title="Rules"
        subtitle="Eternal preferences — always inlined at session start"
        items={eternal}
        onDelete={onDelete}
      />
      <Divider sx={{ borderColor: brand.line }} />
      <MemoryGroup
        title="Episodic"
        subtitle="History surfaced by semantic search"
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
      <Stack direction="row" alignItems="baseline" spacing={2} sx={{ mb: 1 }}>
        <Typography
          sx={{
            fontFamily: fonts.display,
            fontWeight: 600,
            fontSize: "1rem",
            color: brand.text,
          }}
        >
          {title}
        </Typography>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: "0.7rem",
            color: brand.muted,
            letterSpacing: "0.12em",
          }}
        >
          {subtitle}
        </Typography>
        <Box sx={{ flex: 1 }} />
        <Chip
          label={items.length}
          size="small"
          sx={{ fontFamily: fonts.mono, height: 20, fontSize: "0.7rem" }}
        />
      </Stack>
      {items.length === 0 && (
        <Typography sx={{ fontFamily: fonts.body, fontSize: "0.85rem", color: brand.muted }}>
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
      }}
    >
      <Box sx={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={0.75} sx={{ mb: 0.5, flexWrap: "wrap" }}>
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
          sx={{ color: brand.muted, "&:hover": { color: "#ef4444" } }}
        >
          <DeleteIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Box>
  );
}

function DocumentDrawerBody({
  doc,
  loading,
  onClose,
}: {
  doc: DocumentContent | null;
  loading: boolean;
  onClose: () => void;
}) {
  if (!doc) return null;
  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Box
        sx={{
          px: 2,
          py: 1.5,
          borderBottom: `1px solid ${brand.line}`,
          display: "flex",
          alignItems: "center",
          gap: 1,
        }}
      >
        <DescriptionIcon fontSize="small" sx={{ color: brand.cyan }} />
        <Typography
          sx={{
            flex: 1,
            fontFamily: fonts.mono,
            fontSize: "0.85rem",
            color: brand.text,
          }}
          noWrap
        >
          {doc.source_filename}
        </Typography>
        <IconButton size="small" onClick={onClose} sx={{ color: brand.muted }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>
      <Box sx={{ px: 2, py: 1, borderBottom: `1px solid ${brand.line}` }}>
        <Typography
          sx={{ fontFamily: fonts.mono, fontSize: "0.7rem", color: brand.muted }}
        >
          {doc.source_type} · {doc.chunk_count} chunks
          {doc.status ? ` · ${doc.status}` : ""}
          {doc.created_at ? ` · ${new Date(doc.created_at).toLocaleString()}` : ""}
        </Typography>
      </Box>
      <Box sx={{ flex: 1, overflow: "auto", p: 2 }}>
        {loading ? (
          <CircularProgress size={20} sx={{ color: brand.violet2 }} />
        ) : (
          <Typography
            component="pre"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.82rem",
              color: brand.text,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              m: 0,
            }}
          >
            {doc.content || "(empty)"}
          </Typography>
        )}
      </Box>
    </Box>
  );
}
