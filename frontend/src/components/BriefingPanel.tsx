/**
 * BriefingPanel — neo-tokyo clean briefing.
 *
 * Layout: SectionRail (left 210px) + reading column (max 820px).
 * Sections 01–02 (overview, architecture) are always expanded.
 * Sections 03–08 collapse to a one-line row; click to expand.
 *
 * All edit / pin / reset / regenerate handlers are preserved.
 */

import { useEffect, useMemo, useRef, useState } from "react";
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
import EditIcon from "@mui/icons-material/Edit";
import DeleteSweepOutlinedIcon from "@mui/icons-material/DeleteSweepOutlined";
import SaveIcon from "@mui/icons-material/Save";
import CloseIcon from "@mui/icons-material/Close";
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
import SectionRail, { type RailItem } from "./neo/SectionRail";
import PillChain from "./neo/PillChain";
import StatusGlyph, { type GlyphStatus } from "./neo/StatusGlyph";
import { gradientRule, hudLabel } from "./neo/sx";

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

/** Colors cycling for sections 03–08 */
const SECTION_COLORS: Record<BriefingSectionKey, string> = {
  overview: brand.cyan,
  architecture: brand.magenta,
  preferences: brand.violet2,
  important_files: brand.cyan,
  how_it_runs: brand.magenta,
  deployment: brand.violet2,
  dependencies: brand.cyan,
  activity: brand.magenta,
};

/** Sections that are safe/intended to be user-edited. */
const EDITABLE_SECTIONS: BriefingSectionKey[] = [
  "overview",
  "architecture",
  "important_files",
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
  const [data, setData] = useState<BriefingResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingSection, setEditingSection] =
    useState<BriefingSectionKey | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [activeRailIndex, setActiveRailIndex] = useState(0);

  // collapsed state for sections 03–08 (keys: preferences..activity)
  const COLLAPSIBLE_KEYS: BriefingSectionKey[] = [
    "preferences",
    "important_files",
    "how_it_runs",
    "deployment",
    "dependencies",
    "activity",
  ];
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(
    () =>
      Object.fromEntries(COLLAPSIBLE_KEYS.map((k) => [k, true])) as Record<
        string,
        boolean
      >
  );

  // Refs for scrolling into view
  const sectionRefs = useRef<Array<HTMLElement | null>>(
    Array(BRIEFING_SECTIONS.length).fill(null)
  );

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

  const scrollToSection = (i: number) => {
    setActiveRailIndex(i);
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
    return <Alert severity="error">{error}</Alert>;
  }
  if (!data) return null;

  const hasBriefing = Boolean(data.last_generated_at);

  // Build rail items from available sections
  const railItems: RailItem[] = BRIEFING_SECTIONS.filter(
    (key) => data.sections[key]
  ).map((key, i) => ({
    n: String(i + 1).padStart(2, "0"),
    title: SECTION_TITLES[key],
    status: mapStatus(data.sections[key]?.status ?? "auto"),
  }));

  const presentKeys = BRIEFING_SECTIONS.filter((key) => data.sections[key]);

  return (
    <Box sx={{ display: "flex", gap: 5, pb: 6 }}>
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
        sx={{
          flex: 1,
          minWidth: 0,
          maxWidth: 820,
          display: "flex",
          flexDirection: "column",
          gap: 5,
        }}
      >
        {/* Header */}
        <Box
          sx={{
            display: "flex",
            alignItems: "flex-end",
            gap: 2,
            pb: 2.25,
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
            <Typography sx={{ ...hudLabel, color: brand.cyan }}>
              BRIEFING
            </Typography>
            <Typography
              component="h1"
              sx={{
                margin: 0,
                fontSize: 34,
                fontWeight: 700,
                letterSpacing: "-0.4px",
                lineHeight: 1.15,
                fontFamily: fonts.display,
                color: brand.text,
                textShadow: `0 0 18px ${brand.magenta}44`,
              }}
            >
              {data.folder.name}
            </Typography>
            <Typography sx={{ fontSize: 14, color: brand.muted }}>
              Session-start context for coding agents. Edit any section to pin
              it.
            </Typography>
          </Box>
          {hasBriefing && (
            <Tooltip title="Delete this briefing + detailed doc so they regenerate on the next `kioku init`">
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
                  height: 32,
                  fontSize: 12,
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
                component="section"
                ref={(el: HTMLElement | null) => {
                  sectionRefs.current[i] = el;
                }}
                sx={{ display: "flex", flexDirection: "column", gap: 1.75 }}
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
                          "info"
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
                          status
                        );
                        toast.showSuccess(`${SECTION_TITLES[key]} saved.`);
                        setEditingSection(null);
                        await refresh();
                      } catch (err) {
                        toast.showError(
                          err,
                          `Couldn't save ${SECTION_TITLES[key]}.`
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
                          height: 56,
                          px: 0.5,
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
                          component="span"
                          sx={{
                            fontSize: 17,
                            fontWeight: 600,
                            width: 170,
                            flexShrink: 0,
                            fontFamily: fonts.display,
                          }}
                        >
                          {SECTION_TITLES[key]}
                        </Box>
                        <Box
                          component="span"
                          sx={{
                            flex: 1,
                            fontSize: 13,
                            color: brand.muted,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            fontFamily: fonts.body,
                          }}
                        >
                          {SECTION_DESCRIPTIONS[key]}
                        </Box>
                        <StatusGlyph status={mapStatus(section.status)} />
                        <Box
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
                          sx={{
                            py: 2.5,
                            borderBottom: `1px solid ${brand.line}`,
                          }}
                        >
                          <SectionHeading
                            n={n}
                            title={SECTION_TITLES[key]}
                            color={color}
                            status={mapStatus(section.status)}
                            onEdit={() =>
                              EDITABLE_SECTIONS.includes(key)
                                ? setEditingSection(key)
                                : toast.show(
                                    `${SECTION_TITLES[key]} is auto-populated — use Suggest to refresh.`,
                                    "info"
                                  )
                            }
                          />
                          <Box sx={{ mt: 1.75 }}>
                            {editingSection === key ? (
                              <SectionEditor
                                section={section}
                                onSave={async (content, status) => {
                                  try {
                                    await updateBriefingSection(
                                      folderId,
                                      key,
                                      content,
                                      status
                                    );
                                    toast.showSuccess(
                                      `${SECTION_TITLES[key]} saved.`
                                    );
                                    setEditingSection(null);
                                    await refresh();
                                  } catch (err) {
                                    toast.showError(
                                      err,
                                      `Couldn't save ${SECTION_TITLES[key]}.`
                                    );
                                  }
                                }}
                                onCancel={() => setEditingSection(null)}
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
            This deletes the entire briefing <b>and</b> the detailed
            documentation for <b>{data?.folder.name}</b>. To rebuild them, run{" "}
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
        sx={{ fontFamily: fonts.mono, fontSize: 12, color, flexShrink: 0 }}
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
      <Box sx={gradientRule(color)} />
      <StatusGlyph status={status} />
      <Tooltip title="Edit section">
        <IconButton size="small" onClick={onEdit}>
          <EditIcon sx={{ fontSize: 15, color: brand.muted }} />
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
      <>
        <Typography
          sx={{
            fontSize: 20,
            fontWeight: 500,
            lineHeight: 1.5,
            color: brand.text,
          }}
        >
          {lead}
        </Typography>
        {rest && (
          <Typography
            sx={{
              fontSize: 15,
              lineHeight: 1.7,
              color: "#CFC6E6",
            }}
          >
            {rest}
          </Typography>
        )}
      </>
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
      typeof obj.summary === "string"
        ? obj.summary
        : typeof obj.description === "string"
        ? obj.description
        : null;
    if (lead) {
      return (
        <Typography
          sx={{
            fontSize: 20,
            fontWeight: 500,
            lineHeight: 1.5,
            color: brand.text,
          }}
        >
          {lead}
        </Typography>
      );
    }
  }

  // Fallback
  return <SectionReader content={content} />;
}

// ── Architecture (02) ───────────────────────────────────────────────────

function ArchitectureContent({ section }: { section: BriefingSection }) {
  const content = section.content;
  if (!content) return <Empty />;

  // Extract typed fields if content is an object
  let paragraph: string | null = null;
  let dataFlows: Array<{ label: string; steps: string[] }> | null = null;
  let components: Array<{ name: string; role: string; path?: string }> | null =
    null;

  if (
    typeof content === "object" &&
    !Array.isArray(content) &&
    content !== null
  ) {
    const obj = content as Record<string, unknown>;

    // Paragraph description
    if (typeof obj.description === "string") paragraph = obj.description;
    else if (typeof obj.summary === "string") paragraph = obj.summary;

    // data_flow: array of {label, steps} OR a string with "->"
    if (Array.isArray(obj.data_flow)) {
      const raw = obj.data_flow as Array<unknown>;
      // Each item may be {label, steps} or just a string
      dataFlows = raw.flatMap((item) => {
        if (
          item &&
          typeof item === "object" &&
          "label" in (item as object) &&
          "steps" in (item as object)
        ) {
          const it = item as { label: string; steps: unknown };
          const steps = Array.isArray(it.steps)
            ? it.steps.map(String)
            : typeof it.steps === "string"
            ? it.steps.split("->").map((s: string) => s.trim())
            : [];
          return [{ label: it.label, steps }];
        }
        if (typeof item === "string" && item.includes("->")) {
          return [
            {
              label: "",
              steps: item.split("->").map((s: string) => s.trim()),
            },
          ];
        }
        return [];
      });
    } else if (
      typeof obj.data_flow === "string" &&
      obj.data_flow.includes("->")
    ) {
      dataFlows = [
        {
          label: "",
          steps: obj.data_flow.split("->").map((s: string) => s.trim()),
        },
      ];
    }

    // components: array of {name, role, path}
    if (Array.isArray(obj.components)) {
      components = (obj.components as Array<unknown>).filter(
        (c): c is { name: string; role: string; path?: string } =>
          !!c && typeof c === "object" && "name" in (c as object)
      );
    }
  } else if (typeof content === "string") {
    // Check for "->" in a plain string
    if (content.includes("->")) {
      dataFlows = [
        {
          label: "",
          steps: content.split("->").map((s: string) => s.trim()),
        },
      ];
    } else {
      paragraph = content;
    }
  }

  const hasStructured = dataFlows || components;

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.25 }}>
      {/* Paragraph */}
      {paragraph ? (
        <Typography sx={{ fontSize: 15, lineHeight: 1.7, color: "#CFC6E6" }}>
          {paragraph}
        </Typography>
      ) : !hasStructured ? (
        <SectionReader content={content} />
      ) : null}

      {/* DATA FLOW pill chains */}
      {dataFlows && dataFlows.length > 0 && (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.25 }}>
          <Typography sx={{ ...hudLabel }}>DATA FLOW</Typography>
          {dataFlows.map((f, i) => (
            <PillChain
              key={i}
              label={f.label}
              color={i % 2 === 0 ? brand.magenta : brand.cyan}
              steps={f.steps}
            />
          ))}
        </Box>
      )}

      {/* COMPONENTS table */}
      {components && components.length > 0 && (
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.25 }}>
          <Typography sx={{ ...hudLabel }}>COMPONENTS</Typography>
          <Box
            sx={{
              border: `1px solid ${brand.line}`,
              borderRadius: 1,
              overflow: "hidden",
            }}
          >
            {/* Header row */}
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: "180px minmax(0,1fr) 200px",
                p: "8px 14px",
                background: `${brand.magenta}12`,
                fontFamily: fonts.mono,
                fontSize: 10,
                letterSpacing: "0.2em",
                color: brand.magentaGlow,
              }}
            >
              <span>NAME</span>
              <span>ROLE</span>
              <span>PATH</span>
            </Box>
            {components.map((c, i) => (
              <Box
                key={i}
                sx={{
                  display: "grid",
                  gridTemplateColumns: "180px minmax(0,1fr) 200px",
                  gap: 1.5,
                  p: "10px 14px",
                  borderTop: `1px solid ${brand.line}`,
                  fontSize: 14,
                  lineHeight: 1.45,
                }}
              >
                <Box
                  component="span"
                  sx={{ fontWeight: 600, color: brand.text }}
                >
                  {c.name}
                </Box>
                <Box component="span" sx={{ color: "#CFC6E6" }}>
                  {c.role}
                </Box>
                <Box
                  component="span"
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 12,
                    color: brand.cyan,
                  }}
                >
                  {c.path ?? "—"}
                </Box>
              </Box>
            ))}
          </Box>
        </Box>
      )}

      {/* Fallback: if nothing else rendered */}
      {!paragraph && !hasStructured && <SectionReader content={content} />}
    </Box>
  );
}

// ── Meta line (compact provenance) ─────────────────────────────────────

function MetaLine({ section }: { section: BriefingSection }) {
  const source =
    section.provenance === "agent_mcp"
      ? "agent_mcp"
      : section.provenance === "user_ui"
      ? "user_ui"
      : "auto";
  const when = section.updated_at
    ? new Date(section.updated_at).toLocaleDateString()
    : "";
  return (
    <Typography
      sx={{
        fontFamily: fonts.mono,
        fontSize: 11,
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
        in this repo — it generates the briefing and detailed docs as the
        session's first task.
      </Typography>
    </Box>
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

  const save = async () => {
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
