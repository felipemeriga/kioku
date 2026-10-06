/**
 * FolderDetailPage — a single workspace for inspecting one folder.
 *
 *   /folder/:folderId
 *
 * Tabs:
 *   - Briefing (repo folders only) + the detailed architecture doc.
 *   - Documents in this folder subtree — click a card, view content in a drawer.
 *   - Mem0 memories for this folder — rendered by <MemoryPanel/>, which owns
 *     the full memory browser (load, add, delete, rules/episodic grouping).
 */

import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography,
  alpha,
} from "@mui/material";
import DescriptionIcon from "@mui/icons-material/Description";
import { Mem0BrandIcon } from "../components/BrandIcons";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import InsightsIcon from "@mui/icons-material/Insights";
import { useNavigate, useParams } from "react-router-dom";

import BriefingPanel from "../components/BriefingPanel";
import StatusPanel from "../components/StatusPanel";
import DocumentViewerDrawer from "../components/DocumentViewerDrawer";
import { NotionSyncBanner } from "../components/NotionSyncBanner";
import DocumentationPanel from "../components/DocumentationPanel";
import FolderIntegrationsDialog from "../components/FolderIntegrationsDialog";
import MemoryPanel from "../components/MemoryPanel";
import { useToast } from "../components/ToastProvider";
import {
  fetchDocuments,
  fetchFolders,
  fetchMem0Status,
  listFolderMemories,
  type DocumentInfo,
  type Folder,
  type Mem0Status,
  type MemoryRecord,
} from "../lib/api";
import { brand, fonts } from "../theme";

export default function FolderDetailPage() {
  const { folderId } = useParams<{ folderId: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const [folder, setFolder] = useState<Folder | null>(null);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [mem0Status, setMem0Status] = useState<Mem0Status | null>(null);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [viewerFile, setViewerFile] = useState<string | null>(null);
  const [tab, setTab] = useState<
    "briefing" | "documents" | "memory" | "status"
  >("documents");

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

  // Load Mem0 config + memories (for the breadcrumb chip only)
  const loadMem0 = useCallback(async () => {
    if (!folderId) return;
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
    } catch {
      // Non-critical — chip just stays blank
    }
  }, [folderId]);
  useEffect(() => {
    void loadMem0();
  }, [loadMem0]);

  const openDoc = (filename: string) => {
    if (!folderId) return;
    setViewerFile(filename);
  };

  const [integrationsOpen, setIntegrationsOpen] = useState(false);

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
      {/* Folder toolbar: breadcrumb + actions */}
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          gap: 1.5,
          px: 4,
          pt: 2,
          pb: 0,
          borderBottom: `1px solid ${brand.line}`,
        }}
      >
        {/* Breadcrumb + actions row */}
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1.25,
            fontSize: 14,
          }}
        >
          {/* Back arrow */}
          <IconButton
            onClick={() => navigate("/documents?folder=" + folderId)}
            size="small"
            sx={{ color: brand.muted, mr: 0.25 }}
          >
            <ArrowBackIcon fontSize="small" />
          </IconButton>

          {/* Breadcrumb: ⌂ / … / name */}
          <Box
            component="span"
            sx={{ color: brand.muted, fontFamily: fonts.body }}
          >
            ⌂
          </Box>
          <Box
            component="span"
            sx={{ color: brand.lineGlow, fontFamily: fonts.mono }}
          >
            /
          </Box>
          <Box
            component="span"
            sx={{
              fontWeight: 700,
              fontSize: 18,
              color: brand.text,
              fontFamily: fonts.display,
            }}
          >
            {folder?.name ?? "Loading…"}
          </Box>

          {/* Items count chip */}
          <Chip
            label={`${documents.length} items`}
            size="small"
            sx={{
              fontFamily: fonts.mono,
              fontSize: 11,
              height: 22,
              color: brand.cyan,
              border: `1px solid ${brand.cyan}66`,
              bgcolor: "transparent",
            }}
          />

          {/* Memories count chip — display-only status, gated on availability */}
          <Chip
            label={
              mem0Status?.available
                ? `${memories.length} memories`
                : "Memory: repo-only"
            }
            size="small"
            sx={{
              fontFamily: fonts.mono,
              fontSize: 11,
              height: 22,
              color: mem0Status?.available ? brand.magentaGlow : brand.muted,
              border: `1px solid ${
                mem0Status?.available ? `${brand.magenta}66` : brand.line
              }`,
              bgcolor: "transparent",
            }}
          />

          <Box sx={{ flex: 1 }} />

          {/* Integrations — restored original action, cyan-outlined board look */}
          <Button
            size="small"
            variant="outlined"
            onClick={() => setIntegrationsOpen(true)}
            sx={{
              height: 34,
              textTransform: "none",
              borderColor: `${brand.cyan}66`,
              color: brand.cyan,
              fontFamily: fonts.body,
              fontSize: 13,
              fontWeight: 600,
              "&:hover": {
                borderColor: brand.cyan,
                bgcolor: `${brand.cyan}12`,
              },
            }}
          >
            Integrations
          </Button>
        </Box>
      </Box>

      {/* Notion sync status for this folder's root — live progress while a
          sync runs, last-synced/error line when idle, nothing otherwise. */}
      <NotionSyncBanner key={folderId} folderId={folderId} />

      {/* Repo folders get a Briefing tab (the 8-section structured schema);
          other folders have no summary/briefing — only repos do now. */}
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{
          borderBottom: `1px solid ${brand.line}`,
          px: 2,
          "& .MuiTab-root": {
            color: brand.muted,
            fontWeight: 600,
            fontSize: 14,
            minHeight: 44,
            textTransform: "none",
            fontFamily: fonts.display,
          },
          "& .Mui-selected": {
            color: `${brand.cyan} !important`,
            background: `${brand.cyan}12`,
            boxShadow: `inset 0 -2px 0 ${brand.cyan}`,
          },
          "& .MuiTabs-indicator": { display: "none" },
        }}
      >
        {folder?.kind === "repo" && (
          <Tab
            value="briefing"
            label="Briefing"
            icon={<AccountTreeIcon fontSize="small" />}
            iconPosition="start"
          />
        )}
        {folder?.kind === "repo" && (
          <Tab
            value="status"
            label="Status"
            icon={<InsightsIcon fontSize="small" />}
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

        {tab === "status" && folder?.kind === "repo" && (
          <StatusPanel folderId={folderId} />
        )}

        {tab === "documents" && (
          <DocumentsSection
            documents={documents}
            loading={loadingDocs}
            onOpen={openDoc}
          />
        )}

        {tab === "memory" && <MemoryPanel folderId={folderId} />}
      </Box>

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
