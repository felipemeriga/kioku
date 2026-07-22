/**
 * BriefingPanel — the strict 8-section briefing for repo folders.
 *
 * Per-section cards with:
 *   - Read view (markdown-rendered JSON, or plain text for prose)
 *   - Status chip (auto | pinned | hybrid)
 *   - Provenance line: "Edited via UI · <you> · <time ago>"
 *   - Edit button → inline JSON/markdown editor
 *   - Reset → clears pinning + re-runs the section's populator now
 *
 * The panel is only rendered when the folder is a repo (kind='repo').
 * FolderDetailPage handles that gating.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  Stack,
  TextField,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import EditIcon from "@mui/icons-material/Edit";
import DeleteSweepOutlinedIcon from "@mui/icons-material/DeleteSweepOutlined";
import LockIcon from "@mui/icons-material/Lock";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import SaveIcon from "@mui/icons-material/Save";
import CloseIcon from "@mui/icons-material/Close";
import type { SvgIconComponent } from "@mui/icons-material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import TuneOutlinedIcon from "@mui/icons-material/TuneOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import TerminalOutlinedIcon from "@mui/icons-material/TerminalOutlined";
import RocketLaunchOutlinedIcon from "@mui/icons-material/RocketLaunchOutlined";
import Inventory2OutlinedIcon from "@mui/icons-material/Inventory2Outlined";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import {
  BRIEFING_SECTIONS,
  clearBriefing,
  fetchBriefing,
  updateBriefingSection,
  type BriefingResponse,
  type BriefingSection,
  type BriefingSectionKey,
} from "../lib/api";
import { messageFromError, useToast } from "./ToastProvider";
import { brand, fonts } from "../theme";

interface Props {
  folderId: string;
}

const SECTION_TITLES: Record<BriefingSectionKey, string> = {
  overview: "Overview",
  architecture: "Architecture",
  preferences: "Preferences",
  important_files: "Important files",
  how_it_runs: "How it runs",
  deployment: "Deployment",
  dependencies: "Dependencies",
  activity: "Activity",
};

const SECTION_DESCRIPTIONS: Record<BriefingSectionKey, string> = {
  overview: "One-line purpose and a short what/why.",
  architecture:
    "How the system fits together — subsystems, boundaries, data flow.",
  preferences: "Auto-populated from Mem0 [preference] rules.",
  important_files: "3–8 files a fresh agent would want to open first.",
  how_it_runs: "Local dev requirements + setup + run commands.",
  deployment: "Environments, deploy steps, CI/CD notes.",
  dependencies:
    "Auto-parsed from manifests (package.json, pyproject.toml, etc).",
  activity: "Auto-pooled from GitHub sync + Mem0 findings/decisions/sessions.",
};

/** Per-section icon + accent colour — gives each card a distinct visual
 *  anchor so the briefing reads as a set of cards rather than a wall of text. */
const SECTION_VISUALS: Record<
  BriefingSectionKey,
  { icon: SvgIconComponent; color: string }
> = {
  overview: { icon: InfoOutlinedIcon, color: brand.cyan },
  architecture: { icon: AccountTreeOutlinedIcon, color: brand.magenta },
  preferences: { icon: TuneOutlinedIcon, color: brand.violet2 },
  important_files: { icon: DescriptionOutlinedIcon, color: brand.cyan },
  how_it_runs: { icon: TerminalOutlinedIcon, color: brand.magenta },
  deployment: { icon: RocketLaunchOutlinedIcon, color: brand.violet2 },
  dependencies: { icon: Inventory2OutlinedIcon, color: brand.cyan },
  activity: { icon: HistoryOutlinedIcon, color: brand.magenta },
};

/** Sections that are safe/intended to be user-edited. Auto-only sections
 *  (activity, preferences, dependencies) still show but the Edit button is
 *  gated behind an "advanced" click since the auto populator overwrites. */
const EDITABLE_SECTIONS: BriefingSectionKey[] = [
  "overview",
  "architecture",
  "important_files",
  "how_it_runs",
  "deployment",
];

export default function BriefingPanel({ folderId }: Props) {
  const toast = useToast();
  const [data, setData] = useState<BriefingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingSection, setEditingSection] =
    useState<BriefingSectionKey | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const handleClear = async () => {
    setClearing(true);
    try {
      await clearBriefing(folderId);
      setConfirmClear(false);
      toast.show(
        "Briefing cleared. Run `kioku init` in this repo to regenerate it.",
        "info"
      );
      await refresh();
      // clearBriefing also deletes the detailed doc server-side; tell the
      // DocumentationPanel to refetch so it drops the now-deleted doc.
      window.dispatchEvent(
        new CustomEvent("briefing-cleared", { detail: { folderId } })
      );
    } catch (err) {
      toast.showError(err, "Couldn't clear the briefing.");
    } finally {
      setClearing(false);
    }
  };

  const refresh = async () => {
    try {
      const res = await fetchBriefing(folderId);
      setData(res);
      setError(null);
    } catch (err) {
      const msg = messageFromError(err);
      // A non-repo folder legitimately has no briefing (the endpoint 400s with
      // "…only for repo folders"). That's not an error to surface — render
      // nothing so this panel can be dropped on any folder view safely.
      if (/not a repo|only for repo/i.test(msg)) {
        setData(null);
        setError(null);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folderId]);

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }
  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }
  if (!data) return null;

  const hasBriefing = Boolean(data.last_generated_at);

  return (
    <Stack spacing={2}>
      <Stack
        direction="row"
        alignItems="flex-start"
        spacing={1.5}
        sx={{ flexWrap: "wrap" }}
      >
        <Box sx={{ flex: 1, minWidth: 220 }}>
          <Typography
            sx={{
              fontFamily: fonts.display,
              fontSize: "1.4rem",
              color: brand.text,
            }}
          >
            Briefing · {data.folder.name}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Session-start context for coding agents. Auto-populated where
            possible; edit any section to pin it.
          </Typography>
        </Box>
        {hasBriefing && (
          <Tooltip title="Delete this briefing + detailed doc so they regenerate on the next `kioku init`">
            <Button
              size="small"
              variant="outlined"
              startIcon={<DeleteSweepOutlinedIcon sx={{ fontSize: 16 }} />}
              onClick={() => setConfirmClear(true)}
              sx={{
                textTransform: "none",
                color: brand.muted,
                borderColor: brand.line,
                flexShrink: 0,
                "&:hover": {
                  borderColor: brand.magenta,
                  color: brand.magenta,
                  bgcolor: alpha(brand.magenta, 0.06),
                },
              }}
            >
              Clear &amp; regenerate
            </Button>
          </Tooltip>
        )}
      </Stack>

      {hasBriefing ? (
        BRIEFING_SECTIONS.map((key) => (
          <SectionCard
            key={key}
            sectionKey={key}
            section={data.sections[key]}
            editing={editingSection === key}
            onStartEdit={() =>
              EDITABLE_SECTIONS.includes(key)
                ? setEditingSection(key)
                : toast.show(
                    `${SECTION_TITLES[key]} is auto-populated — use Suggest to refresh.`,
                    "info"
                  )
            }
            onCancelEdit={() => setEditingSection(null)}
            onSave={async (content, status) => {
              try {
                await updateBriefingSection(folderId, key, content, status);
                toast.showSuccess(`${SECTION_TITLES[key]} saved.`);
                setEditingSection(null);
                await refresh();
              } catch (err) {
                toast.showError(err, `Couldn't save ${SECTION_TITLES[key]}.`);
              }
            }}
          />
        ))
      ) : (
        <NotGenerated />
      )}

      <Dialog
        open={confirmClear}
        onClose={() => !clearing && setConfirmClear(false)}
        PaperProps={{
          sx: { bgcolor: brand.surface, border: `1px solid ${brand.line}` },
        }}
      >
        <DialogTitle sx={{ fontFamily: fonts.display, color: brand.text }}>
          Clear the briefing?
        </DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ color: brand.muted }}>
            This deletes the entire briefing <b>and</b> the detailed
            documentation for <b>{data.folder.name}</b>. To rebuild them, run{" "}
            <Box
              component="code"
              sx={{
                fontFamily: fonts.mono,
                color: brand.cyan,
                bgcolor: brand.surface2,
                px: 0.5,
                borderRadius: 0.5,
              }}
            >
              kioku init
            </Box>{" "}
            in the repo — it regenerates everything as its first task.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button
            onClick={() => setConfirmClear(false)}
            disabled={clearing}
            sx={{ textTransform: "none", color: brand.muted }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            startIcon={<DeleteSweepOutlinedIcon fontSize="small" />}
            onClick={handleClear}
            disabled={clearing}
            sx={{ textTransform: "none" }}
          >
            {clearing ? "Clearing…" : "Clear briefing"}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

// ── Empty state: no briefing generated yet ─────────────────────────────

function NotGenerated() {
  return (
    <Box
      sx={{
        border: `1px dashed ${brand.line}`,
        borderRadius: 2,
        p: 4,
        textAlign: "center",
        bgcolor: alpha("#0b0b0f", 0.3),
      }}
    >
      <TerminalOutlinedIcon sx={{ fontSize: 34, color: brand.cyan, mb: 1 }} />
      <Typography
        sx={{
          fontFamily: fonts.display,
          fontSize: "1.1rem",
          color: brand.text,
          mb: 0.5,
        }}
      >
        No briefing yet
      </Typography>
      <Typography variant="body2" sx={{ color: brand.muted, mb: 2 }}>
        Run{" "}
        <Box
          component="code"
          sx={{
            fontFamily: fonts.mono,
            color: brand.cyan,
            bgcolor: brand.surface2,
            px: 0.5,
            borderRadius: 0.5,
          }}
        >
          kioku init
        </Box>{" "}
        in this repo — it generates the briefing and detailed docs as the
        session's first task.
      </Typography>
    </Box>
  );
}

// ── Section card ────────────────────────────────────────────────────────

function SectionCard({
  sectionKey,
  section,
  editing,
  onStartEdit,
  onCancelEdit,
  onSave,
}: {
  sectionKey: BriefingSectionKey;
  section: BriefingSection;
  editing: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSave: (content: unknown, status: "pinned" | "auto") => Promise<void>;
}) {
  const visual = SECTION_VISUALS[sectionKey];
  const Icon = visual.icon;
  return (
    <Box
      sx={{
        border: `1px solid ${brand.line}`,
        borderLeft: `3px solid ${alpha(visual.color, 0.6)}`,
        borderRadius: 1.5,
        p: 1.75,
        bgcolor: alpha("#0b0b0f", 0.4),
        transition: "border-color 0.15s, background-color 0.15s",
        "&:hover": {
          borderColor: alpha(visual.color, 0.4),
          borderLeftColor: visual.color,
          bgcolor: alpha("#0b0b0f", 0.55),
        },
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1.25} sx={{ mb: 1 }}>
        <Box
          sx={{
            width: 30,
            height: 30,
            borderRadius: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            bgcolor: alpha(visual.color, 0.12),
            border: `1px solid ${alpha(visual.color, 0.25)}`,
            flexShrink: 0,
          }}
        >
          <Icon sx={{ fontSize: 17, color: visual.color }} />
        </Box>
        <Typography
          sx={{
            fontFamily: fonts.display,
            fontSize: "1.05rem",
            color: brand.text,
            flex: 1,
          }}
        >
          {SECTION_TITLES[sectionKey]}
        </Typography>
        <StatusChip status={section.status} />
        {!editing && (
          <Tooltip title="Edit section">
            <IconButton size="small" onClick={onStartEdit}>
              <EditIcon sx={{ fontSize: 15, color: brand.muted }} />
            </IconButton>
          </Tooltip>
        )}
      </Stack>

      <Typography
        variant="caption"
        sx={{ color: brand.muted, display: "block", mb: 1 }}
      >
        {SECTION_DESCRIPTIONS[sectionKey]}
      </Typography>

      {editing ? (
        <SectionEditor
          section={section}
          onSave={onSave}
          onCancel={onCancelEdit}
        />
      ) : (
        <SectionReader content={section.content} />
      )}

      <ProvenanceRow section={section} />
    </Box>
  );
}

function StatusChip({ status }: { status: BriefingSection["status"] }) {
  if (status === "pinned") {
    return (
      <Chip
        size="small"
        icon={<LockIcon sx={{ fontSize: 12 }} />}
        label="PINNED"
        sx={{
          height: 20,
          fontSize: "0.62rem",
          fontFamily: fonts.mono,
          letterSpacing: "0.14em",
          bgcolor: alpha(brand.violet2, 0.15),
          color: brand.violet2,
          "& .MuiChip-icon": { color: brand.violet2 },
        }}
      />
    );
  }
  if (status === "hybrid") {
    return (
      <Chip
        size="small"
        label="HYBRID"
        sx={{
          height: 20,
          fontSize: "0.62rem",
          fontFamily: fonts.mono,
          letterSpacing: "0.14em",
          bgcolor: alpha(brand.cyan, 0.15),
          color: brand.cyan,
        }}
      />
    );
  }
  return (
    <Chip
      size="small"
      icon={<AutoAwesomeIcon sx={{ fontSize: 12 }} />}
      label="AUTO"
      sx={{
        height: 20,
        fontSize: "0.62rem",
        fontFamily: fonts.mono,
        letterSpacing: "0.14em",
        bgcolor: alpha(brand.muted, 0.15),
        color: brand.muted,
        "& .MuiChip-icon": { color: brand.muted },
      }}
    />
  );
}

function ProvenanceRow({ section }: { section: BriefingSection }) {
  const when = section.updated_at
    ? new Date(section.updated_at).toLocaleString()
    : "";
  const source =
    section.provenance === "agent_mcp"
      ? "coding agent (via MCP)"
      : section.provenance === "user_ui"
      ? "you (via UI)"
      : "auto-populator";
  const by = section.updated_by ? ` — ${section.updated_by}` : "";
  return (
    <Typography
      variant="caption"
      sx={{
        fontFamily: fonts.mono,
        fontSize: "0.68rem",
        color: brand.muted,
        display: "block",
        mt: 1,
        opacity: 0.7,
      }}
    >
      Last edit: {source}
      {by} · {when}
    </Typography>
  );
}

// ── Reader: render section content ─────────────────────────────────────

function SectionReader({ content }: { content: unknown }) {
  if (content == null) return <Empty />;
  if (typeof content === "string") {
    if (!content.trim()) return <Empty />;
    return (
      <Typography
        sx={{
          fontFamily: fonts.body,
          fontSize: "0.9rem",
          color: brand.text,
          whiteSpace: "pre-wrap",
          lineHeight: 1.55,
        }}
      >
        {content}
      </Typography>
    );
  }
  if (Array.isArray(content)) {
    if (content.length === 0) return <Empty />;
    return (
      <Stack spacing={0.5}>
        {content.map((item, i) => (
          <ArrayItem key={i} item={item} />
        ))}
      </Stack>
    );
  }
  if (typeof content === "object") {
    const obj = content as Record<string, unknown>;
    if (Object.keys(obj).length === 0) return <Empty />;
    return (
      <Stack spacing={0.75}>
        {Object.entries(obj).map(([k, v]) => (
          <ObjectField key={k} label={k} value={v} />
        ))}
      </Stack>
    );
  }
  return <Empty />;
}

function ArrayItem({ item }: { item: unknown }) {
  if (typeof item === "string") {
    return (
      <Box
        sx={{
          pl: 1.5,
          borderLeft: `2px solid ${alpha(brand.violet2, 0.4)}`,
          fontSize: "0.86rem",
          color: brand.text,
          lineHeight: 1.5,
        }}
      >
        {item}
      </Box>
    );
  }
  if (item && typeof item === "object") {
    const obj = item as Record<string, unknown>;
    return (
      <Box
        sx={{
          pl: 1.5,
          borderLeft: `2px solid ${alpha(brand.violet2, 0.4)}`,
        }}
      >
        {Object.entries(obj).map(([k, v]) => (
          <Typography
            key={k}
            sx={{ fontSize: "0.84rem", color: brand.text, lineHeight: 1.5 }}
          >
            <Box
              component="span"
              sx={{ color: brand.cyan, fontFamily: fonts.mono }}
            >
              {k}:
            </Box>{" "}
            {String(v)}
          </Typography>
        ))}
      </Box>
    );
  }
  return null;
}

function ObjectField({ label, value }: { label: string; value: unknown }) {
  if (value == null || (typeof value === "string" && !value.trim())) {
    return (
      <Typography
        sx={{ fontSize: "0.82rem", color: brand.muted, fontStyle: "italic" }}
      >
        {label}: (not set)
      </Typography>
    );
  }
  if (Array.isArray(value)) {
    return (
      <Box>
        <Typography
          sx={{
            fontSize: "0.75rem",
            fontFamily: fonts.mono,
            color: brand.muted,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            mb: 0.4,
          }}
        >
          {label}
        </Typography>
        <Stack spacing={0.4}>
          {value.map((v, i) => (
            <ArrayItem key={i} item={v} />
          ))}
        </Stack>
      </Box>
    );
  }
  if (typeof value === "object") {
    return <SectionReader content={value} />;
  }
  // Prose-y fields (summary, description, data_flow, …) and any long string read
  // better as a labelled paragraph than an inline "LABEL value" run.
  const str = String(value);
  const PROSE_KEYS = new Set([
    "summary",
    "description",
    "purpose",
    "data_flow",
    "local_dev",
    "ci_cd_notes",
    "how_to_deploy",
  ]);
  if (PROSE_KEYS.has(label) || str.length > 80) {
    return (
      <Box>
        <Typography
          sx={{
            fontSize: "0.72rem",
            fontFamily: fonts.mono,
            color: brand.muted,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            mb: 0.4,
          }}
        >
          {label}
        </Typography>
        <Typography
          sx={{
            fontSize: "0.9rem",
            color: brand.text,
            lineHeight: 1.6,
            whiteSpace: "pre-wrap",
          }}
        >
          {str}
        </Typography>
      </Box>
    );
  }
  return (
    <Typography
      sx={{ fontSize: "0.88rem", color: brand.text, lineHeight: 1.5 }}
    >
      <Box
        component="span"
        sx={{
          fontFamily: fonts.mono,
          color: brand.cyan,
          fontSize: "0.75rem",
          mr: 0.75,
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        {label}
      </Box>
      {str}
    </Typography>
  );
}

function Empty() {
  return (
    <Typography
      variant="body2"
      sx={{ color: brand.muted, fontStyle: "italic", py: 1 }}
    >
      Not filled in yet. Click Edit to add content, or wait for the next regen
      to auto-populate.
    </Typography>
  );
}

// ── Editor: raw JSON textarea for now. Phase 4.1 could grow per-shape editors ──

function SectionEditor({
  section,
  onSave,
  onCancel,
}: {
  section: BriefingSection;
  onSave: (content: unknown, status: "pinned" | "auto") => Promise<void>;
  onCancel: () => void;
}) {
  const initial = useMemo(() => {
    const c = section.content;
    if (typeof c === "string") return c;
    return JSON.stringify(c, null, 2);
  }, [section.content]);
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    // Try JSON parse; if it fails, save as string (prose section).
    let parsed: unknown = draft;
    try {
      parsed = JSON.parse(draft);
    } catch {
      parsed = draft;
    }
    try {
      await onSave(parsed, "pinned");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <TextField
        multiline
        fullWidth
        minRows={4}
        maxRows={20}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        InputProps={{
          sx: {
            fontFamily: fonts.mono,
            fontSize: "0.85rem",
            bgcolor: alpha("#000", 0.2),
          },
        }}
      />
      <Divider sx={{ my: 1, borderColor: brand.line }} />
      <Stack direction="row" spacing={1} justifyContent="flex-end">
        <Button
          size="small"
          startIcon={<CloseIcon fontSize="small" />}
          onClick={onCancel}
          disabled={busy}
          sx={{ textTransform: "none", color: brand.muted }}
        >
          Cancel
        </Button>
        <Button
          size="small"
          variant="contained"
          startIcon={<SaveIcon fontSize="small" />}
          onClick={save}
          disabled={busy}
          sx={{ textTransform: "none" }}
        >
          {busy ? "Saving…" : "Save + Pin"}
        </Button>
      </Stack>
    </Box>
  );
}
