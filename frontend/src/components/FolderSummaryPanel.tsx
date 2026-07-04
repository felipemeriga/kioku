import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  IconButton,
  Menu,
  MenuItem,
  Stack,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RefreshIcon from "@mui/icons-material/Refresh";
import ArrowDropDownIcon from "@mui/icons-material/ArrowDropDown";
import CompareArrowsIcon from "@mui/icons-material/CompareArrows";
import HistoryIcon from "@mui/icons-material/History";
import {
  fetchFolderSummary,
  regenerateFolderSummary,
  type FolderSummaryContent,
  type FolderSummaryRow,
} from "../lib/api";
import { brand, fonts } from "../theme";

interface Props {
  folderId: string;
  folderName: string;
}

function relativeTime(iso: string): string {
  const now = Date.now();
  const then = new Date(iso).getTime();
  const s = Math.max(1, Math.floor((now - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

// KIND — solid state badge. Signals "this row is a full/delta/seed summary."
// Uses opaque brand color at low intensity so it reads as a status marker.
function KindChip({ kind }: { kind: FolderSummaryRow["kind"] }) {
  const color =
    kind === "full" ? brand.violet2 : kind === "delta" ? brand.cyan : brand.muted;
  return (
    <Chip
      label={kind.toUpperCase()}
      size="small"
      sx={{
        fontFamily: fonts.mono,
        fontSize: "0.62rem",
        fontWeight: 600,
        letterSpacing: "0.14em",
        color: brand.ink,
        bgcolor: color,
        height: 20,
        borderRadius: 0.75,
        px: 0.25,
        "& .MuiChip-label": { px: 1 },
      }}
    />
  );
}

// CHANGES — softer data chip. Signals "here's what changed" — read like a stat.
function ChangesChip({ row }: { row: FolderSummaryRow }) {
  const { added = [], removed = [], modified = [] } = row.changed_files || {
    added: [],
    removed: [],
    modified: [],
  };
  const total = added.length + removed.length + modified.length;
  if (total === 0) return null;
  return (
    <Tooltip
      title={
        <Box sx={{ fontFamily: fonts.mono, fontSize: "0.72rem", lineHeight: 1.6 }}>
          {added.map((f) => (
            <div key={"a-" + f} style={{ color: "#7ee787" }}>+ {f}</div>
          ))}
          {modified.map((f) => (
            <div key={"m-" + f} style={{ color: "#79c0ff" }}>~ {f}</div>
          ))}
          {removed.map((f) => (
            <div key={"r-" + f} style={{ color: "#ffa198" }}>− {f}</div>
          ))}
        </Box>
      }
    >
      <Chip
        icon={<CompareArrowsIcon sx={{ fontSize: 13, ml: "6px !important" }} />}
        label={`${total} file${total > 1 ? "s" : ""} changed`}
        size="small"
        sx={{
          fontFamily: fonts.mono,
          fontSize: "0.65rem",
          color: brand.muted,
          bgcolor: "transparent",
          border: `1px solid ${brand.line}`,
          height: 22,
          borderRadius: 0.75,
          "&:hover": {
            bgcolor: alpha(brand.cyan, 0.06),
            color: brand.cyan,
            borderColor: alpha(brand.cyan, 0.4),
          },
        }}
      />
    </Tooltip>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <Typography
      variant="overline"
      sx={{
        fontFamily: fonts.mono,
        fontSize: "0.6rem",
        letterSpacing: "0.24em",
        color: brand.muted,
        display: "block",
        mb: 0.75,
      }}
    >
      {children}
    </Typography>
  );
}

function BulletList({ items }: { items: string[] }) {
  return (
    <Stack spacing={0.5}>
      {items.map((item, i) => (
        <Typography
          key={i}
          sx={{
            fontFamily: fonts.body,
            fontSize: "0.85rem",
            color: brand.text,
            lineHeight: 1.5,
            pl: 1.5,
            position: "relative",
            "&::before": {
              content: '""',
              position: "absolute",
              left: 0,
              top: "0.55rem",
              width: 5,
              height: 5,
              borderRadius: "50%",
              bgcolor: brand.violet2,
            },
          }}
        >
          {item}
        </Typography>
      ))}
    </Stack>
  );
}

export default function FolderSummaryPanel({ folderId, folderName }: Props) {
  const [row, setRow] = useState<FolderSummaryRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [regenMode, setRegenMode] = useState<"auto" | "full" | "delta">("auto");
  const [expanded, setExpanded] = useState(true);
  const [showDiff, setShowDiff] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [modeMenuAnchor, setModeMenuAnchor] = useState<HTMLElement | null>(null);
  const [pollUntil, setPollUntil] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetchFolderSummary(folderId);
      setRow(res.summary);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [folderId]);

  useEffect(() => {
    setLoading(true);
    setRow(null);
    load();
  }, [load]);

  // While a regeneration is running, poll for the new row.
  useEffect(() => {
    if (!pollUntil) return;
    const interval = setInterval(async () => {
      if (Date.now() > pollUntil) {
        setPollUntil(null);
        setRegenerating(false);
        return;
      }
      const res = await fetchFolderSummary(folderId).catch(() => null);
      if (res?.summary && (!row || res.summary.id !== row.id)) {
        setRow(res.summary);
        setPollUntil(null);
        setRegenerating(false);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [pollUntil, folderId, row]);

  const handleRegenerate = async (mode: "auto" | "full" | "delta") => {
    setModeMenuAnchor(null);
    setRegenMode(mode);
    setRegenerating(true);
    setError(null);
    try {
      await regenerateFolderSummary(folderId, mode);
      setPollUntil(Date.now() + 5 * 60 * 1000);
    } catch (e) {
      setError(String(e));
      setRegenerating(false);
    }
  };

  // Defensive: legacy or malformed rows might store array fields as strings
  // or nulls (Anthropic tool-use isn't strict-schema). Normalize before render
  // so the panel never crashes on wrong shape.
  const asArray = <T,>(v: unknown): T[] =>
    Array.isArray(v) ? (v as T[]) : [];
  const rawContent = row?.content || null;
  const content: FolderSummaryContent | null = rawContent
    ? ({
        title: rawContent.title || "",
        purpose: rawContent.purpose || "",
        overview: rawContent.overview || "",
        themes: asArray<{ name: string; description: string }>(rawContent.themes),
        key_documents: asArray<{ filename: string; role: string }>(
          rawContent.key_documents
        ),
        key_facts: asArray<string>(rawContent.key_facts),
        entities: asArray<string>(rawContent.entities),
        gotchas: asArray<string>(rawContent.gotchas),
      } as FolderSummaryContent)
    : null;
  const rawPrev = row?.previous_content || null;
  const previousContent: FolderSummaryContent | null = rawPrev
    ? ({
        title: rawPrev.title || "",
        purpose: rawPrev.purpose || "",
        overview: rawPrev.overview || "",
        themes: asArray<{ name: string; description: string }>(rawPrev.themes),
        key_documents: asArray<{ filename: string; role: string }>(
          rawPrev.key_documents
        ),
        key_facts: asArray<string>(rawPrev.key_facts),
        entities: asArray<string>(rawPrev.entities),
        gotchas: asArray<string>(rawPrev.gotchas),
      } as FolderSummaryContent)
    : null;

  const generatedRel = row ? relativeTime(row.generated_at) : null;

  // The diff surface shows the FILE-level changes that triggered this summary,
  // not string-diffing the two summary contents (which is subjective — the LLM
  // often paraphrases so line-level diffing is noisy). changed_files is the
  // ground truth from the diff logic in services/folder_summary/diff.py.
  const fileDiff = useMemo(() => {
    if (!row) return null;
    const cf = row.changed_files || { added: [], removed: [], modified: [] };
    const total = cf.added.length + cf.removed.length + cf.modified.length;
    if (total === 0) return null;
    return cf;
  }, [row]);

  return (
    <Box
      sx={{
        mb: 2,
        borderRadius: 2,
        border: `1px solid ${brand.line}`,
        bgcolor: brand.surface,
        overflow: "hidden",
        position: "relative",
        boxShadow: `0 1px 0 0 ${alpha("#000", 0.4)}, 0 8px 24px -12px ${alpha(brand.violet, 0.2)}`,
        // Thin gradient accent bar down the left edge, matching brand.
        "&::before": {
          content: '""',
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 3,
          background: `linear-gradient(180deg, ${brand.violet2}, ${brand.cyan})`,
          opacity: 0.7,
        },
      }}
    >
      {/* Header — always visible */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          px: 2.25,
          py: 1.4,
          cursor: "pointer",
          borderBottom: expanded ? `1px solid ${brand.line}` : "none",
          background: expanded
            ? `linear-gradient(90deg, ${alpha(brand.violet, 0.1)} 0%, ${alpha(brand.violet, 0.02)} 40%, transparent 100%)`
            : "transparent",
          transition: "background 0.15s",
          "&:hover": { bgcolor: alpha(brand.violet, 0.06) },
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <AutoAwesomeIcon sx={{ fontSize: 20, color: brand.violet2 }} />
        <Typography
          sx={{
            fontFamily: fonts.display,
            fontSize: "0.95rem",
            fontWeight: 600,
            color: brand.text,
            flex: 1,
          }}
        >
          Folder orientation
        </Typography>

        {row && <KindChip kind={row.kind} />}
        {row && <ChangesChip row={row} />}
        {generatedRel && (
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.7rem",
              color: brand.muted,
            }}
          >
            {generatedRel}
          </Typography>
        )}

        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <Tooltip title="Regenerate">
            <span>
              <IconButton
                size="small"
                disabled={regenerating}
                onClick={(e) => {
                  e.stopPropagation();
                  handleRegenerate(regenMode);
                }}
                sx={{ color: brand.muted }}
              >
                {regenerating ? (
                  <CircularProgress size={14} sx={{ color: brand.violet2 }} />
                ) : (
                  <RefreshIcon sx={{ fontSize: 16 }} />
                )}
              </IconButton>
            </span>
          </Tooltip>
          <IconButton
            size="small"
            disabled={regenerating}
            onClick={(e) => {
              e.stopPropagation();
              setModeMenuAnchor(e.currentTarget);
            }}
            sx={{ color: brand.muted, p: 0 }}
          >
            <ArrowDropDownIcon sx={{ fontSize: 18 }} />
          </IconButton>
          <Menu
            anchorEl={modeMenuAnchor}
            open={Boolean(modeMenuAnchor)}
            onClose={() => setModeMenuAnchor(null)}
            slotProps={{
              paper: {
                sx: {
                  bgcolor: brand.surface,
                  border: `1px solid ${brand.line}`,
                  minWidth: 240,
                },
              },
            }}
          >
            {[
              { mode: "auto", label: "Auto", hint: "Skip if nothing changed, else delta" },
              { mode: "delta", label: "Delta", hint: "Patch only the docs that changed" },
              { mode: "full", label: "Full rebuild", hint: "Resummarize every doc" },
            ].map((opt) => (
              <MenuItem
                key={opt.mode}
                onClick={() => handleRegenerate(opt.mode as "auto" | "full" | "delta")}
                sx={{ display: "block", py: 1 }}
              >
                <Typography
                  sx={{
                    fontFamily: fonts.body,
                    fontSize: "0.86rem",
                    fontWeight: 600,
                    color: brand.text,
                    lineHeight: 1.25,
                  }}
                >
                  {opt.label}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: fonts.body,
                    fontSize: "0.72rem",
                    color: brand.muted,
                    lineHeight: 1.3,
                  }}
                >
                  {opt.hint}
                </Typography>
              </MenuItem>
            ))}
          </Menu>
        </Box>

        <IconButton size="small" sx={{ color: brand.muted, p: 0.5 }}>
          <ExpandMoreIcon
            sx={{
              fontSize: 20,
              transform: expanded ? "rotate(0deg)" : "rotate(-90deg)",
              transition: "transform 0.15s",
            }}
          />
        </IconButton>
      </Box>

      <Collapse in={expanded} timeout="auto">
        <Box sx={{ p: 2.5 }}>
          {loading && (
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                gap: 1.5,
                color: brand.muted,
                py: 2,
              }}
            >
              <CircularProgress size={16} sx={{ color: brand.violet2 }} />
              <Typography sx={{ fontFamily: fonts.body, fontSize: "0.85rem" }}>
                Loading orientation…
              </Typography>
            </Box>
          )}

          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          {!loading && !row && !error && (
            <Stack spacing={1.5}>
              <Typography
                sx={{
                  fontFamily: fonts.body,
                  fontSize: "0.9rem",
                  color: brand.muted,
                }}
              >
                No orientation summary yet for <b>{folderName}</b>. The nightly
                cron will build one, or generate one now.
              </Typography>
              <Box>
                <Button
                  variant="contained"
                  size="small"
                  disabled={regenerating}
                  startIcon={
                    regenerating ? (
                      <CircularProgress size={14} sx={{ color: "inherit" }} />
                    ) : (
                      <AutoAwesomeIcon sx={{ fontSize: 16 }} />
                    )
                  }
                  onClick={() => handleRegenerate("full")}
                  sx={{
                    bgcolor: brand.violet,
                    "&:hover": { bgcolor: brand.violetDeep },
                    fontFamily: fonts.body,
                  }}
                >
                  {regenerating ? "Generating…" : "Generate orientation"}
                </Button>
              </Box>
            </Stack>
          )}

          {content && (
            <Stack spacing={2.5} sx={{ maxWidth: "78ch" }}>
              {/* Purpose + overview */}
              <Box>
                <Typography
                  sx={{
                    fontFamily: fonts.display,
                    fontSize: "1.05rem",
                    fontWeight: 600,
                    color: brand.text,
                    mb: 0.5,
                  }}
                >
                  {content.title || folderName}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: fonts.body,
                    fontSize: "0.9rem",
                    color: brand.cyan,
                    fontStyle: "italic",
                    mb: 1,
                  }}
                >
                  {content.purpose}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: fonts.body,
                    fontSize: "0.9rem",
                    color: brand.text,
                    lineHeight: 1.6,
                  }}
                >
                  {content.overview}
                </Typography>
              </Box>

              {content.themes && content.themes.length > 0 && (
                <>
                  <Divider sx={{ borderColor: brand.line }} />
                  <Box>
                    <SectionHeading>Themes</SectionHeading>
                    <Stack spacing={1.25}>
                      {content.themes.map((t, i) => (
                        <Box
                          key={i}
                          sx={{
                            pl: 1.5,
                            borderLeft: `2px solid ${alpha(brand.violet2, 0.5)}`,
                            py: 0.25,
                          }}
                        >
                          <Typography
                            sx={{
                              fontFamily: fonts.body,
                              fontSize: "0.86rem",
                              fontWeight: 600,
                              color: brand.violet2,
                              mb: 0.25,
                            }}
                          >
                            {t.name}
                          </Typography>
                          <Typography
                            sx={{
                              fontFamily: fonts.body,
                              fontSize: "0.84rem",
                              color: brand.text,
                              lineHeight: 1.55,
                            }}
                          >
                            {t.description}
                          </Typography>
                        </Box>
                      ))}
                    </Stack>
                  </Box>
                </>
              )}

              {content.key_documents && content.key_documents.length > 0 && (
                <>
                  <Divider sx={{ borderColor: brand.line }} />
                  <Box>
                    <SectionHeading>Key documents</SectionHeading>
                    <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                      {content.key_documents.map((d, i) => (
                        <Box
                          key={i}
                          sx={{
                            display: "grid",
                            gridTemplateColumns: {
                              xs: "1fr",
                              sm: "minmax(160px, 22ch) 1fr",
                            },
                            gap: { xs: 0.25, sm: 1.5 },
                            py: 0.6,
                            px: 1,
                            borderRadius: 1,
                            transition: "background 0.15s",
                            "&:hover": { bgcolor: alpha(brand.violet, 0.05) },
                          }}
                        >
                          <Typography
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: "0.78rem",
                              color: brand.cyan,
                              lineHeight: 1.5,
                              wordBreak: "break-all",
                            }}
                          >
                            {d.filename}
                          </Typography>
                          <Typography
                            sx={{
                              fontFamily: fonts.body,
                              fontSize: "0.83rem",
                              color: brand.muted,
                              lineHeight: 1.5,
                            }}
                          >
                            {d.role}
                          </Typography>
                        </Box>
                      ))}
                    </Stack>
                  </Box>
                </>
              )}

              {content.key_facts && content.key_facts.length > 0 && (
                <>
                  <Divider sx={{ borderColor: brand.line }} />
                  <Box>
                    <SectionHeading>Key facts</SectionHeading>
                    <BulletList items={content.key_facts} />
                  </Box>
                </>
              )}

              {content.gotchas && content.gotchas.length > 0 && (
                <>
                  <Divider sx={{ borderColor: brand.line }} />
                  <Box>
                    <SectionHeading>Gotchas</SectionHeading>
                    <Stack spacing={0.5}>
                      {content.gotchas.map((g, i) => (
                        <Typography
                          key={i}
                          sx={{
                            fontFamily: fonts.body,
                            fontSize: "0.83rem",
                            color: brand.amber,
                            lineHeight: 1.5,
                            pl: 1.5,
                            position: "relative",
                            "&::before": {
                              content: '"⚠"',
                              position: "absolute",
                              left: 0,
                              color: brand.amberLight,
                              fontSize: "0.75rem",
                            },
                          }}
                        >
                          {g}
                        </Typography>
                      ))}
                    </Stack>
                  </Box>
                </>
              )}

              {content.entities && content.entities.length > 0 && (
                <>
                  <Divider sx={{ borderColor: brand.line }} />
                  <Box>
                    <SectionHeading>Entities</SectionHeading>
                    <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                      {content.entities.map((e, i) => (
                        <Chip
                          key={i}
                          label={e}
                          size="small"
                          sx={{
                            fontFamily: fonts.body,
                            fontSize: "0.75rem",
                            color: brand.muted,
                            bgcolor: alpha(brand.muted, 0.08),
                            border: `1px solid ${brand.line}`,
                            height: 22,
                          }}
                        />
                      ))}
                    </Box>
                  </Box>
                </>
              )}

              {fileDiff && previousContent ? (
                <>
                  <Divider sx={{ borderColor: brand.line }} />
                  <Box>
                    <Box
                      sx={{
                        display: "flex",
                        alignItems: "center",
                        gap: 0.75,
                        cursor: "pointer",
                        color: brand.cyan,
                        "&:hover": { color: brand.violet2 },
                      }}
                      onClick={() => setShowDiff(!showDiff)}
                    >
                      <HistoryIcon sx={{ fontSize: 15 }} />
                      <Typography
                        sx={{
                          fontFamily: fonts.mono,
                          fontSize: "0.7rem",
                          letterSpacing: "0.1em",
                          textTransform: "uppercase",
                        }}
                      >
                        {showDiff ? "Hide" : "Show"} files that changed since
                        previous summary
                      </Typography>
                    </Box>
                    <Collapse in={showDiff}>
                      <Box sx={{ mt: 1.5, pl: 2 }}>
                        {fileDiff.added.map((f, i) => (
                          <Typography
                            key={"a" + i}
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: "0.78rem",
                              color: brand.green,
                            }}
                          >
                            + added &nbsp;&nbsp;{f}
                          </Typography>
                        ))}
                        {fileDiff.modified.map((f, i) => (
                          <Typography
                            key={"m" + i}
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: "0.78rem",
                              color: brand.cyan,
                            }}
                          >
                            ~ changed {f}
                          </Typography>
                        ))}
                        {fileDiff.removed.map((f, i) => (
                          <Typography
                            key={"r" + i}
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: "0.78rem",
                              color: brand.amber,
                            }}
                          >
                            − removed{" "}
                            <span style={{ textDecoration: "line-through" }}>
                              {f}
                            </span>
                          </Typography>
                        ))}
                      </Box>
                    </Collapse>
                  </Box>
                </>
              ) : null}

              <Box
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  pt: 1,
                  borderTop: `1px dashed ${brand.line}`,
                }}
              >
                <Typography
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: "0.65rem",
                    color: brand.muted,
                  }}
                >
                  {row?.doc_count ?? 0} docs · {row?.input_tokens ?? 0} in ·{" "}
                  {row?.output_tokens ?? 0} out
                  {row?.duration_ms ? ` · ${(row.duration_ms / 1000).toFixed(1)}s` : ""}
                </Typography>
                <Typography
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: "0.65rem",
                    color: brand.muted,
                  }}
                >
                  This summary is loaded at session-start via the MCP tool
                  get_folder_orientation.
                </Typography>
              </Box>
            </Stack>
          )}
        </Box>
      </Collapse>
    </Box>
  );
}
