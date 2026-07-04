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

function KindChip({ kind }: { kind: FolderSummaryRow["kind"] }) {
  const color =
    kind === "full" ? brand.violet2 : kind === "delta" ? brand.cyan : brand.muted;
  return (
    <Chip
      label={kind.toUpperCase()}
      size="small"
      sx={{
        fontFamily: fonts.mono,
        fontSize: "0.65rem",
        letterSpacing: "0.12em",
        color,
        bgcolor: alpha(color, 0.12),
        border: `1px solid ${alpha(color, 0.35)}`,
        height: 20,
      }}
    />
  );
}

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
        <Box sx={{ fontFamily: fonts.mono, fontSize: "0.7rem" }}>
          {added.length > 0 && <div>+{added.join(", +")}</div>}
          {modified.length > 0 && <div>~{modified.join(", ~")}</div>}
          {removed.length > 0 && <div>-{removed.join(", -")}</div>}
        </Box>
      }
    >
      <Chip
        icon={<CompareArrowsIcon sx={{ fontSize: 14 }} />}
        label={`${total} file${total > 1 ? "s" : ""} changed`}
        size="small"
        sx={{
          fontFamily: fonts.mono,
          fontSize: "0.65rem",
          color: brand.cyan,
          bgcolor: alpha(brand.cyan, 0.1),
          border: `1px solid ${alpha(brand.cyan, 0.3)}`,
          height: 22,
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

  const content: FolderSummaryContent | null = row?.content || null;
  const previousContent: FolderSummaryContent | null =
    row?.previous_content || null;

  const generatedRel = row ? relativeTime(row.generated_at) : null;
  const diff = useMemo(() => {
    if (!content || !previousContent) return null;
    const currFacts = content.key_facts || [];
    const prevFacts = previousContent.key_facts || [];
    const added = currFacts.filter((f) => !prevFacts.includes(f));
    const removed = prevFacts.filter((f) => !currFacts.includes(f));
    return { added, removed };
  }, [content, previousContent]);

  return (
    <Box
      sx={{
        mb: 2,
        borderRadius: 2,
        border: `1px solid ${brand.line}`,
        bgcolor: alpha(brand.surface, 0.6),
        overflow: "hidden",
      }}
    >
      {/* Header — always visible */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          px: 2,
          py: 1.25,
          cursor: "pointer",
          borderBottom: expanded ? `1px solid ${brand.line}` : "none",
          background: expanded
            ? `linear-gradient(90deg, ${alpha(brand.violet, 0.08)}, transparent)`
            : "transparent",
          "&:hover": { bgcolor: alpha(brand.violet, 0.05) },
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <AutoAwesomeIcon sx={{ fontSize: 18, color: brand.violet2 }} />
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
          >
            <MenuItem onClick={() => handleRegenerate("auto")}>
              Auto (skip / delta / full)
            </MenuItem>
            <MenuItem onClick={() => handleRegenerate("delta")}>
              Delta (only changed docs)
            </MenuItem>
            <MenuItem onClick={() => handleRegenerate("full")}>
              Full rebuild
            </MenuItem>
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

          {!loading && !row && (
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
            <Stack spacing={2.5}>
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
                    <Stack spacing={1}>
                      {content.themes.map((t, i) => (
                        <Box key={i}>
                          <Typography
                            sx={{
                              fontFamily: fonts.body,
                              fontSize: "0.85rem",
                              fontWeight: 600,
                              color: brand.violet2,
                            }}
                          >
                            {t.name}
                          </Typography>
                          <Typography
                            sx={{
                              fontFamily: fonts.body,
                              fontSize: "0.83rem",
                              color: brand.text,
                              lineHeight: 1.5,
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
                    <Stack spacing={0.75}>
                      {content.key_documents.map((d, i) => (
                        <Box
                          key={i}
                          sx={{ display: "flex", gap: 1, alignItems: "baseline" }}
                        >
                          <Typography
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: "0.78rem",
                              color: brand.cyan,
                              flexShrink: 0,
                            }}
                          >
                            {d.filename}
                          </Typography>
                          <Typography
                            sx={{
                              fontFamily: fonts.body,
                              fontSize: "0.82rem",
                              color: brand.muted,
                            }}
                          >
                            — {d.role}
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

              {previousContent && diff && (diff.added.length || diff.removed.length) ? (
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
                        Diff vs previous version
                      </Typography>
                    </Box>
                    <Collapse in={showDiff}>
                      <Box sx={{ mt: 1.5, pl: 2 }}>
                        {diff.added.map((f, i) => (
                          <Typography
                            key={"a" + i}
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: "0.78rem",
                              color: brand.green,
                            }}
                          >
                            + {f}
                          </Typography>
                        ))}
                        {diff.removed.map((f, i) => (
                          <Typography
                            key={"r" + i}
                            sx={{
                              fontFamily: fonts.mono,
                              fontSize: "0.78rem",
                              color: brand.amber,
                            }}
                          >
                            − {f}
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
