/**
 * BriefingPanel — neo-tokyo clean briefing.
 *
 * Layout: SectionRail (left 210px) + reading column (max 820px).
 * Sections 01–02 (overview, architecture) are always expanded.
 * Remaining sections collapse to a one-line row; click to expand.
 *
 * All edit / pin / reset / regenerate handlers are preserved.
 */

import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ReadableContent } from "./agent-evidence/ReadableContent";
import { qk } from "../lib/queryKeys";
import {
  Alert,
  Box,
  Button,
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
import DeleteSweepOutlinedIcon from "@mui/icons-material/DeleteSweepOutlined";
import SaveIcon from "@mui/icons-material/Save";
import CloseIcon from "@mui/icons-material/Close";
import {
  BRIEFING_SECTIONS,
  clearBriefing,
  fetchBriefing,
  updateBriefingSection,
  type BriefingSection,
  type BriefingSectionKey,
} from "../lib/api";
import { messageFromError, useToast } from "./ToastProvider";
import { brand, fonts } from "../theme";
import SectionRail, { type RailItem } from "./neo/SectionRail";
import { type GlyphStatus } from "./neo/StatusGlyph";
import { gradientRule } from "./neo/sx";

interface Props {
  folderId: string;
}

const SECTION_TITLES: Record<BriefingSectionKey, string> = {
  overview: "Introduction",
  architecture: "Components",
  how_it_runs: "How it runs",
  deployment: "Deployment",
  activity: "Activity",
};

const SECTION_DESCRIPTIONS: Record<BriefingSectionKey, string> = {
  overview: "Purpose and scope.",
  architecture: "Responsibilities, interfaces and key paths.",
  how_it_runs: "Prerequisites, setup, run modes, and checks.",
  deployment: "Environments, deploy steps, CI/CD notes.",
  activity: "Recent repository activity from git history.",
};

/** Colors cycling for the remaining sections. */
const SECTION_COLORS: Record<BriefingSectionKey, string> = {
  overview: brand.cyan,
  architecture: brand.magenta,
  how_it_runs: brand.magenta,
  deployment: brand.violet2,
  activity: brand.magenta,
};

/** Sections that are safe/intended to be user-edited. */
const EDITABLE_SECTIONS: BriefingSectionKey[] = [
  "overview",
  "architecture",
  "how_it_runs",
  "deployment",
];

function mapStatus(s: BriefingSection["status"]): GlyphStatus {
  if (s === "pinned") return "pinned";
  if (s === "hybrid") return "hybrid";
  return "auto";
}

export default function BriefingPanel({ folderId }: Props) {
  const toast = useToast();
  const queryClient = useQueryClient();

  // Cached briefing; non-repo folders report "not a repo", which we treat as
  // simply "no briefing" (null) rather than an error.
  const briefingQuery = useQuery({
    queryKey: qk.briefing(folderId),
    queryFn: async () => {
      try {
        return await fetchBriefing(folderId);
      } catch (err) {
        if (/not a repo|only for repo/i.test(messageFromError(err)))
          return null;
        throw err;
      }
    },
  });
  const data = briefingQuery.data ?? null;
  const loading = briefingQuery.isPending;
  const error = briefingQuery.isError
    ? messageFromError(briefingQuery.error)
    : null;
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: qk.briefing(folderId) });

  const [editingSection, setEditingSection] =
    useState<BriefingSectionKey | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [activeRailIndex, setActiveRailIndex] = useState(0);

  // Collapsed state for sections after the overview and architecture.
  const COLLAPSIBLE_KEYS: BriefingSectionKey[] = [
    "how_it_runs",
    "deployment",
    "activity",
  ];
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(
    () =>
      Object.fromEntries(COLLAPSIBLE_KEYS.map((k) => [k, true])) as Record<
        string,
        boolean
      >,
  );

  // Refs for scrolling into view
  const sectionRefs = useRef<Array<HTMLElement | null>>(
    Array(BRIEFING_SECTIONS.length).fill(null),
  );

  const handleClear = async () => {
    setClearing(true);
    try {
      await clearBriefing(folderId);
      setConfirmClear(false);
      toast.show(
        "Briefing cleared. Run `kioku init` in this repo to regenerate it.",
        "info",
      );
      await refresh();
    } catch (err) {
      toast.showError(err, "Couldn't clear the briefing.");
    } finally {
      setClearing(false);
    }
  };

  const scrollToSection = (i: number) => {
    setActiveRailIndex(i);
    const key = presentKeys[i];
    if (key) setCollapsed((previous) => ({ ...previous, [key]: false }));
    sectionRefs.current[i]?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }
  if (error) {
    return (
      <Alert
        severity="error"
        action={<Button onClick={() => void refresh()}>Retry</Button>}
      >
        {error}
      </Alert>
    );
  }
  if (!data) return null;

  const hasBriefing = Boolean(data.last_generated_at);

  // Build rail items from available sections
  const railItems: RailItem[] = BRIEFING_SECTIONS.filter(
    (key) => data.sections[key],
  ).map((key, i) => ({
    n: String(i + 1).padStart(2, "0"),
    title: SECTION_TITLES[key],
    status: mapStatus(data.sections[key]?.status ?? "auto"),
  }));

  const presentKeys = BRIEFING_SECTIONS.filter((key) => data.sections[key]);

  return (
    <Box
      className="briefing-layout"
      sx={{
        display: "flex",
        flexDirection: { xs: "column", lg: "row" },
        gap: { xs: 3, lg: 4 },
        pb: 6,
      }}
    >
      {/* Left: section rail */}
      {hasBriefing && (
        <SectionRail
          items={railItems}
          activeIndex={activeRailIndex}
          onSelect={scrollToSection}
        />
      )}

      {/* Right: reading column */}
      <Box
        className="briefing-panel"
        sx={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: 0,
          border: `1px solid ${brand.line}`,
          borderRadius: 2,
          overflow: "hidden",
          backgroundColor: brand.surface,
        }}
      >
        {/* Header */}
        <Box
          className="briefing-panel-header"
          sx={{
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 2,
            p: 3,
            borderBottom: `1px solid ${brand.line}`,
          }}
        >
          <Box
            sx={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              gap: 0.75,
            }}
          >
            <Typography
              component="h1"
              sx={{
                margin: 0,
                fontSize: 23,
                fontWeight: 600,
                letterSpacing: "-0.4px",
                lineHeight: 1.15,
                fontFamily: fonts.display,
                color: brand.text,
                textShadow: "none",
              }}
            >
              Repository briefing
            </Typography>
            <Typography sx={{ fontSize: 14, color: brand.muted }}>
              Session-start context shared with your coding agents.
            </Typography>
          </Box>
          {hasBriefing && (
            <Tooltip title="Clear the briefing so it regenerates on the next `kioku init`">
              <Button
                size="small"
                variant="outlined"
                startIcon={<DeleteSweepOutlinedIcon sx={{ fontSize: 14 }} />}
                onClick={() => setConfirmClear(true)}
                sx={{
                  textTransform: "none",
                  color: brand.muted,
                  borderColor: brand.line,
                  flexShrink: 0,
                  minHeight: 44,
                  fontSize: 14,
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
        </Box>

        {hasBriefing ? (
          <>
            {/* Expanded sections: overview (01) and architecture (02) */}
            {presentKeys.slice(0, 2).map((key, i) => (
              <Box
                key={key}
                className="briefing-section"
                component="section"
                ref={(el: HTMLElement | null) => {
                  sectionRefs.current[i] = el;
                }}
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  p: 3,
                  borderBottom: `1px solid ${brand.line}`,
                }}
              >
                <SectionHeading
                  n={String(i + 1).padStart(2, "0")}
                  title={SECTION_TITLES[key]}
                  color={SECTION_COLORS[key]}
                  status={mapStatus(data.sections[key]?.status ?? "auto")}
                  onEdit={() =>
                    EDITABLE_SECTIONS.includes(key)
                      ? setEditingSection(key)
                      : toast.show(
                          `${SECTION_TITLES[key]} is auto-populated — use Suggest to refresh.`,
                          "info",
                        )
                  }
                />

                {editingSection === key ? (
                  <SectionEditor
                    section={data.sections[key]!}
                    onSave={async (content, status) => {
                      try {
                        await updateBriefingSection(
                          folderId,
                          key,
                          content,
                          status,
                        );
                        toast.showSuccess(`${SECTION_TITLES[key]} saved.`);
                        setEditingSection(null);
                        await refresh();
                      } catch (err) {
                        toast.showError(
                          err,
                          `Couldn't save ${SECTION_TITLES[key]}.`,
                        );
                      }
                    }}
                    onCancel={() => setEditingSection(null)}
                  />
                ) : key === "overview" ? (
                  <OverviewContent section={data.sections[key]!} />
                ) : key === "architecture" ? (
                  <ArchitectureContent section={data.sections[key]!} />
                ) : null}

                <MetaLine section={data.sections[key]!} />
              </Box>
            ))}

            {/* Collapsible sections 03–08 */}
            {presentKeys.length > 2 && (
              <Box
                className="briefing-section"
                component="section"
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  borderTop: `1px solid ${brand.line}`,
                }}
              >
                {presentKeys.slice(2).map((key, idx) => {
                  const globalIdx = idx + 2;
                  const isCollapsed = collapsed[key] === true;
                  const n = String(globalIdx + 1).padStart(2, "0");
                  const color = SECTION_COLORS[key];
                  const section = data.sections[key]!;
                  return (
                    <Box
                      key={key}
                      ref={(el: HTMLElement | null) => {
                        sectionRefs.current[globalIdx] = el;
                      }}
                    >
                      {/* Row header — always visible */}
                      <Box
                        className="collapsed-section"
                        component="button"
                        onClick={() => {
                          setCollapsed((prev) => ({
                            ...prev,
                            [key]: !isCollapsed,
                          }));
                          setActiveRailIndex(globalIdx);
                        }}
                        aria-expanded={!isCollapsed}
                        sx={{
                          display: "flex",
                          alignItems: "center",
                          gap: 1.5,
                          minHeight: 68,
                          py: 1.75,
                          px: 3,
                          width: "100%",
                          border: 0,
                          borderBottom: `1px solid ${brand.line}`,
                          background: "transparent",
                          color: brand.text,
                          textAlign: "left",
                          cursor: "pointer",
                          "&:hover": {
                            bgcolor: alpha(brand.magenta, 0.04),
                          },
                        }}
                      >
                        <Box
                          className="section-number"
                          component="span"
                          sx={{
                            fontFamily: fonts.mono,
                            fontSize: 12,
                            color,
                            flexShrink: 0,
                          }}
                        >
                          {n}
                        </Box>
                        <Box
                          className="section-title"
                          component="span"
                          sx={{
                            fontSize: 17,
                            fontWeight: 600,
                            width: { xs: "auto", md: 170 },
                            flexShrink: 0,
                            fontFamily: fonts.display,
                          }}
                        >
                          {SECTION_TITLES[key]}
                        </Box>
                        <Box
                          className="section-description"
                          component="span"
                          sx={{
                            flex: 1,
                            fontSize: 13,
                            color: brand.muted,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "normal",
                            display: { xs: "none", md: "block" },
                            fontFamily: fonts.body,
                          }}
                        >
                          {SECTION_DESCRIPTIONS[key]}
                        </Box>
                        <Typography
                          component="span"
                          sx={{ fontSize: 13, color: brand.muted }}
                        >
                          {section.status === "pinned"
                            ? "Pinned"
                            : section.status === "hybrid"
                              ? "Mixed"
                              : "Generated"}
                        </Typography>
                        <Box
                          className="section-chevron"
                          component="span"
                          sx={{
                            fontFamily: fonts.mono,
                            fontSize: 14,
                            color: brand.muted,
                            ml: 0.5,
                            transition: "transform 0.2s",
                            transform: isCollapsed
                              ? "rotate(0deg)"
                              : "rotate(90deg)",
                          }}
                        >
                          ▸
                        </Box>
                      </Box>

                      {/* Expanded content */}
                      {!isCollapsed && (
                        <Box
                          className="briefing-section"
                          sx={{
                            py: 2.5,
                            borderBottom: `1px solid ${brand.line}`,
                          }}
                        >
                          <Button
                            aria-label="Edit section"
                            sx={{ alignSelf: "flex-end", color: brand.cyan }}
                            onClick={() =>
                              EDITABLE_SECTIONS.includes(key)
                                ? setEditingSection(key)
                                : toast.show(
                                    `${SECTION_TITLES[key]} is auto-populated — use Suggest to refresh.`,
                                    "info",
                                  )
                            }
                          >
                            Edit
                          </Button>
                          <Box
                            sx={{
                              mt: 1.75,
                              px: { xs: 2, md: 3 },
                              maxWidth: 900,
                            }}
                          >
                            {editingSection === key ? (
                              <SectionEditor
                                section={section}
                                onSave={async (content, status) => {
                                  try {
                                    await updateBriefingSection(
                                      folderId,
                                      key,
                                      content,
                                      status,
                                    );
                                    toast.showSuccess(
                                      `${SECTION_TITLES[key]} saved.`,
                                    );
                                    setEditingSection(null);
                                    await refresh();
                                  } catch (err) {
                                    toast.showError(
                                      err,
                                      `Couldn't save ${SECTION_TITLES[key]}.`,
                                    );
                                  }
                                }}
                                onCancel={() => setEditingSection(null)}
                              />
                            ) : key === "how_it_runs" ? (
                              <HowItRunsContent content={section.content} />
                            ) : key === "deployment" || key === "activity" ? (
                              <ReadingSection
                                content={section.content}
                                section={key}
                              />
                            ) : (
                              <SectionReader content={section.content} />
                            )}
                          </Box>
                          <MetaLine section={section} />
                        </Box>
                      )}
                    </Box>
                  );
                })}
              </Box>
            )}
          </>
        ) : (
          <NotGenerated />
        )}
      </Box>

      {/* Clear & regenerate confirm dialog */}
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
            This clears the briefing for <b>{data?.folder.name}</b>. Authored
            reference documents stay available. To rebuild the briefing, run{" "}
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
            in the repo.
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
    </Box>
  );
}

// ── Section heading row ─────────────────────────────────────────────────

function SectionHeading({
  n,
  title,
  color,
  status,
  onEdit,
}: {
  n: string;
  title: string;
  color: string;
  status: GlyphStatus;
  onEdit: () => void;
}) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
      <Box
        component="span"
        sx={{
          display: "none",
          fontFamily: fonts.mono,
          fontSize: 12,
          color,
          flexShrink: 0,
        }}
      >
        {n}
      </Box>
      <Typography
        component="h2"
        sx={{
          margin: 0,
          fontSize: 20,
          fontWeight: 600,
          fontFamily: fonts.display,
          color: brand.text,
        }}
      >
        {title}
      </Typography>
      {/* gradient rule */}
      <Box className="section-title-rule" sx={gradientRule(color)} />
      <Typography
        sx={{
          ml: "auto",
          color: status === "pinned" ? brand.amber : brand.muted,
          fontSize: 13,
        }}
      >
        {status === "pinned"
          ? "Pinned"
          : status === "hybrid"
            ? "Mixed"
            : "Generated"}
      </Typography>
      <Tooltip title="Edit section">
        <IconButton size="small" onClick={onEdit}>
          <Typography sx={{ color: brand.cyan, fontSize: 14 }}>Edit</Typography>
        </IconButton>
      </Tooltip>
    </Box>
  );
}

// ── Overview (01) ───────────────────────────────────────────────────────

function OverviewContent({ section }: { section: BriefingSection }) {
  const content = section.content;
  if (!content) return <Empty />;

  // If content is a plain string, treat the first sentence as the lead.
  if (typeof content === "string") {
    const trimmed = content.trim();
    if (!trimmed) return <Empty />;
    // Split on first sentence boundary for the lead.
    const dotIdx = trimmed.indexOf(". ");
    const lead =
      dotIdx > 0 ? trimmed.slice(0, dotIdx + 1) : trimmed.slice(0, 200);
    const rest = dotIdx > 0 ? trimmed.slice(dotIdx + 2) : "";
    return (
      <Stack spacing={1.5} sx={{ maxWidth: "78ch" }}>
        <Typography
          sx={{
            fontSize: 17,
            fontWeight: 400,
            lineHeight: 1.75,
            color: brand.text,
          }}
        >
          {lead}
        </Typography>
        {rest && <BriefingMarkdown content={rest} />}
      </Stack>
    );
  }

  // Object with a 'summary' or 'description' field
  if (
    typeof content === "object" &&
    content !== null &&
    !Array.isArray(content)
  ) {
    const obj = content as Record<string, unknown>;
    const lead =
      typeof obj.purpose === "string" && obj.purpose.trim()
        ? obj.purpose
        : typeof obj.summary === "string"
          ? obj.summary
          : typeof obj.description === "string"
            ? obj.description
            : null;
    const description =
      typeof obj.description === "string" && obj.description !== lead
        ? obj.description
        : null;
    if (lead) {
      return (
        <Stack spacing={1.5} sx={{ maxWidth: "78ch" }}>
          <Typography
            sx={{ fontSize: 17, lineHeight: 1.65, color: brand.text }}
          >
            {lead}
          </Typography>
          {description &&
            (description.length > 600 ? (
              <Box
                component="details"
                sx={{
                  color: brand.muted,
                  "& summary": { cursor: "pointer", mb: 1 },
                }}
              >
                <summary>More context</summary>
                <BriefingMarkdown content={description} />
              </Box>
            ) : (
              <BriefingMarkdown content={description} />
            ))}
        </Stack>
      );
    }
  }

  // Fallback
  return <SectionReader content={content} />;
}

// ── Architecture (02) ───────────────────────────────────────────────────

function ArchitectureContent({ section }: { section: BriefingSection }) {
  const content = section.content;
  if (!content || typeof content !== "object" || Array.isArray(content))
    return <SectionReader content={content} />;
  const record = content as Record<string, unknown>;
  const components = Array.isArray(record.components)
    ? record.components.filter(
        (item): item is { name: string; role?: string; path?: string } =>
          !!item && typeof item === "object" && typeof item.name === "string",
      )
    : [];
  if (!components.length) return <SectionReader content={content} />;
  const summary =
    typeof record.summary === "string" ? record.summary : record.description;
  return (
    <Stack spacing={2.5} sx={{ minWidth: 0 }}>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "minmax(0, 1fr)",
            xl: "repeat(2, minmax(0, 1fr))",
          },
          gap: 2,
        }}
      >
        {components.map((component, index) => (
          <Box
            key={index}
            component="article"
            sx={{
              border: `1px solid ${brand.line}`,
              borderRadius: 1,
              p: 2.25,
              minWidth: 0,
              bgcolor: brand.surface2,
            }}
          >
            <Typography
              component="h3"
              sx={{ fontWeight: 650, fontSize: 17, mb: 1 }}
            >
              {component.name}
            </Typography>
            {typeof component.role === "string" && (
              <BriefingMarkdown content={component.role} />
            )}
            {typeof component.path === "string" && (
              <Box
                component="code"
                sx={{
                  display: "block",
                  mt: 1.5,
                  fontFamily: fonts.mono,
                  fontSize: 12,
                  color: brand.cyan,
                  overflowWrap: "anywhere",
                }}
              >
                {component.path}
              </Box>
            )}
          </Box>
        ))}
      </Box>
      {Boolean(summary || record.data_flow) && (
        <Box
          component="details"
          sx={{
            maxWidth: "76ch",
            color: brand.muted,
            "& summary": { cursor: "pointer", fontWeight: 600, mb: 1.5 },
          }}
        >
          <summary>How components connect</summary>
          {typeof summary === "string" && (
            <BriefingMarkdown content={summary} />
          )}
          {Boolean(record.data_flow) && (
            <SectionReader content={record.data_flow} />
          )}
        </Box>
      )}
    </Stack>
  );
}

// ── Meta line (compact provenance) ─────────────────────────────────────

function MetaLine({ section }: { section: BriefingSection }) {
  const source =
    section.provenance === "agent_mcp"
      ? "Updated by an agent"
      : section.provenance === "user_ui"
        ? "Edited in Kioku"
        : "Generated";
  const when = section.updated_at
    ? new Date(section.updated_at).toLocaleDateString()
    : "";
  return (
    <Typography
      className="briefing-meta"
      sx={{
        fontFamily: fonts.mono,
        fontSize: 13,
        color: brand.muted,
        mt: 0.5,
      }}
    >
      {source}
      {when ? ` · ${when}` : ""}
    </Typography>
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
        in this repo to generate its five-section briefing.
      </Typography>
    </Box>
  );
}

// ── Reader: render section content ─────────────────────────────────────

function SectionReader({ content }: { content: unknown }) {
  if (content == null) return <Empty />;
  if (typeof content === "string") {
    if (!content.trim()) return <Empty />;
    return <BriefingMarkdown content={content} />;
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
      <Stack spacing={2.5} sx={{ maxWidth: "78ch" }}>
        {Object.entries(obj).map(([k, v]) => (
          <ObjectField key={k} label={k} value={v} />
        ))}
      </Stack>
    );
  }
  return <Empty />;
}

function ReadingHeading({ children }: { children: string }) {
  return (
    <Typography
      component="h3"
      sx={{
        fontSize: 15,
        fontWeight: 700,
        color: brand.text,
        borderLeft: `2px solid ${brand.magenta}`,
        bgcolor: alpha(brand.magenta, 0.06),
        px: 1.75,
        py: 1,
        mb: 1.5,
      }}
    >
      {children}
    </Typography>
  );
}

function ReadingSection({
  content,
  section,
}: {
  content: unknown;
  section: "deployment" | "activity";
}) {
  if (!content || typeof content !== "object" || Array.isArray(content)) {
    return <SectionReader content={content} />;
  }
  const fields = Object.entries(content as Record<string, unknown>).filter(
    ([, value]) =>
      value != null &&
      value !== "" &&
      (!Array.isArray(value) || value.length > 0),
  );
  if (!fields.length) return <Empty />;
  const order =
    section === "deployment"
      ? ["environments", "how_to_deploy", "ci_cd_notes"]
      : ["summary", "highlights"];
  fields.sort(([a], [b]) => {
    const ai = order.indexOf(a);
    const bi = order.indexOf(b);
    return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
  });
  return (
    <Stack spacing={3.5} sx={{ maxWidth: "76ch" }}>
      {fields.map(([label, value]) => (
        <Box key={label} component="section">
          <ReadingHeading>{fieldHeading(label)}</ReadingHeading>
          <ObjectField label={label} value={value} hideHeading />
        </Box>
      ))}
    </Stack>
  );
}

function HowItRunsContent({ content }: { content: unknown }) {
  if (!content || typeof content !== "object" || Array.isArray(content)) {
    return <SectionReader content={content} />;
  }

  const guide = content as Record<string, unknown>;
  const requirements = Array.isArray(guide.requirements)
    ? guide.requirements.filter(
        (item): item is string => typeof item === "string",
      )
    : [];
  const localDev = typeof guide.local_dev === "string" ? guide.local_dev : "";
  const setupAlreadyCovered =
    /^#{1,4}\s*(prerequisites|requirements|before you start)/im.test(localDev);

  return (
    <Stack spacing={3.5} sx={{ maxWidth: "76ch" }}>
      {requirements.length > 0 && (
        <Box
          component={setupAlreadyCovered ? "details" : "div"}
          sx={{
            borderLeft: `2px solid ${brand.cyan}`,
            bgcolor: alpha(brand.cyan, 0.04),
            px: 2,
            py: 1.5,
          }}
        >
          {setupAlreadyCovered ? (
            <Box
              component="summary"
              sx={{ color: brand.cyan, cursor: "pointer", fontWeight: 700 }}
            >
              Requirements at a glance ({requirements.length})
            </Box>
          ) : (
            <Typography
              component="h3"
              sx={{ fontSize: 14, fontWeight: 700, color: brand.cyan, mb: 1 }}
            >
              Before you start
            </Typography>
          )}
          <Box component="ul" sx={{ pl: 2.5, my: 0 }}>
            {requirements.map((requirement, index) => (
              <Box
                component="li"
                key={index}
                sx={{ mb: 0.75, color: brand.text }}
              >
                {requirement}
              </Box>
            ))}
          </Box>
        </Box>
      )}
      {localDev ? <BriefingMarkdown content={localDev} guide /> : <Empty />}
    </Stack>
  );
}

function BriefingMarkdown({
  content,
  guide = false,
}: {
  content: string;
  guide?: boolean;
}) {
  return (
    <Box
      sx={{
        fontFamily: fonts.body,
        fontSize: "0.94rem",
        color: brand.text,
        lineHeight: 1.8,
        overflowWrap: "anywhere",
        "& p": { my: 1.5 },
        "& h2, & h3, & h4": {
          color: brand.text,
          mt: 2.5,
          mb: 1,
          lineHeight: 1.3,
        },
        "& h2": { fontSize: "1.15rem" },
        "& h3": { fontSize: "1.03rem" },
        "& h4": { fontSize: "0.95rem" },
        ...(guide && {
          "& h2, & h3": {
            color: brand.text,
            borderLeft: `2px solid ${brand.magenta}`,
            bgcolor: alpha(brand.magenta, 0.06),
            px: 1.75,
            py: 1,
            mt: 3.5,
            mb: 1.75,
            lineHeight: 1.4,
          },
          "& h2:first-of-type, & h3:first-of-type": { mt: 0 },
        }),
        "& ul, & ol": { pl: 3, my: 1.5 },
        "& li": { mb: 0.5 },
        "& pre": {
          overflowX: "auto",
          p: 1.5,
          border: `1px solid ${brand.line}`,
          borderRadius: 1,
          bgcolor: brand.ink,
          fontFamily: fonts.mono,
          fontSize: "0.82rem",
        },
        "& :not(pre) > code": {
          color: brand.cyan,
          fontFamily: fonts.mono,
          fontSize: "0.84em",
          bgcolor: alpha(brand.cyan, 0.07),
          px: 0.4,
          py: 0.15,
          borderRadius: 0.5,
        },
        "& table": {
          display: "block",
          overflowX: "auto",
          borderCollapse: "collapse",
        },
        "& th, & td": { border: `1px solid ${brand.line}`, px: 1, py: 0.5 },
      }}
    >
      <ReadableContent text={content} />
    </Box>
  );
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
        <BriefingMarkdown content={item} />
      </Box>
    );
  }
  if (item && typeof item === "object") {
    return (
      <Box
        sx={{ pl: 1.5, borderLeft: `2px solid ${alpha(brand.violet2, 0.4)}` }}
      >
        <SectionReader content={item} />
      </Box>
    );
  }
  return null;
}

function fieldHeading(label: string): string {
  const headings: Record<string, string> = {
    requirements: "Before you start",
    local_dev: "Run and verify",
    environments: "Environments",
    how_to_deploy: "Release steps",
    ci_cd_notes: "CI and delivery",
    summary: "Summary",
    highlights: "Recent highlights",
  };
  return (
    headings[label] ??
    label.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())
  );
}

function ObjectField({
  label,
  value,
  hideHeading = false,
}: {
  label: string;
  value: unknown;
  hideHeading?: boolean;
}) {
  const heading = fieldHeading(label);
  if (value == null || (typeof value === "string" && !value.trim())) {
    return null;
  }
  if (Array.isArray(value)) {
    return (
      <Box>
        {!hideHeading && (
          <Typography
            sx={{
              fontSize: "0.75rem",
              fontFamily: fonts.mono,
              color: brand.muted,
              textTransform: "none",
              letterSpacing: "0.08em",
              mb: 0.4,
            }}
          >
            {heading}
          </Typography>
        )}
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
        {!hideHeading && (
          <Typography
            sx={{
              fontSize: "0.8125rem",
              fontFamily: fonts.mono,
              color: brand.muted,
              textTransform: "none",
              letterSpacing: "0.08em",
              mb: 0.4,
            }}
          >
            {heading}
          </Typography>
        )}
        <BriefingMarkdown content={str} />
      </Box>
    );
  }
  return (
    <Typography
      sx={{ fontSize: "0.88rem", color: brand.text, lineHeight: 1.5 }}
    >
      {!hideHeading && (
        <Box
          component="span"
          sx={{
            fontFamily: fonts.mono,
            color: brand.cyan,
            fontSize: "0.75rem",
            mr: 0.75,
            textTransform: "none",
            letterSpacing: "0.08em",
          }}
        >
          {label}
        </Box>
      )}
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

// ── Editor ──────────────────────────────────────────────────────────────

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
  const invalid = !draft.trim() || draft.length > 50000;

  const save = async () => {
    if (invalid) return;
    setBusy(true);
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
        error={invalid}
        helperText={
          !draft.trim()
            ? "Add content before saving."
            : draft.length > 50000
              ? "Keep the section under 50,000 characters."
              : undefined
        }
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
          disabled={busy || invalid}
          sx={{ textTransform: "none" }}
        >
          {busy ? "Saving…" : "Save + Pin"}
        </Button>
      </Stack>
    </Box>
  );
}
