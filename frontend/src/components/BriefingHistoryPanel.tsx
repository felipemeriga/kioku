/**
 * BriefingHistoryPanel — version timeline, per-section diffs, and restore.
 *
 * Layout:
 *  - Left column: version list (newest-first), trigger badge, time-ago, changed-section chips, Restore button.
 *  - Right column (when 2 versions selected): per-section diff (added=green, removed=red), unchanged collapsed.
 *
 * Conventions: StatusPanel loading/error pattern, CornerCard / fonts.mono / brand colors, React Query.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { diffLines } from "diff";
import { qk } from "../lib/queryKeys";
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import RefreshIcon from "@mui/icons-material/Refresh";
import RestoreIcon from "@mui/icons-material/Restore";
import {
  fetchBriefingHistory,
  fetchBriefingVersion,
  restoreBriefingVersion,
} from "../lib/api";
import { serializeSection } from "../lib/serializeSection";
import { brand, fonts } from "../theme";
import CornerCard from "./neo/CornerCard";

// ── helpers ──────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── sub-components ────────────────────────────────────────────────────────────

interface SectionDiffProps {
  sectionKey: string;
  oldText: string;
  newText: string;
}

function SectionDiff({ sectionKey, oldText, newText }: SectionDiffProps) {
  const parts = diffLines(oldText, newText);
  const hasChanges = parts.some((p) => p.added || p.removed);

  return (
    <Box data-testid={`diff-${sectionKey}`} sx={{ mb: 2 }}>
      <Typography
        sx={{
          fontFamily: fonts.mono,
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: hasChanges ? brand.cyan : brand.muted,
          mb: 0.5,
        }}
      >
        {sectionKey}
        {!hasChanges && (
          <Box
            component="span"
            sx={{ ml: 1, color: brand.dim, fontWeight: 400 }}
          >
            — unchanged
          </Box>
        )}
      </Typography>
      {hasChanges && (
        <Box
          sx={{
            fontFamily: fonts.mono,
            fontSize: 12,
            lineHeight: 1.5,
            border: `1px solid ${brand.line}`,
            borderRadius: 1,
            overflow: "hidden",
          }}
        >
          {parts.map((part, i) => {
            if (!part.added && !part.removed) return null;
            const bg = part.added ? `${brand.green}18` : `${brand.magenta}18`;
            const color = part.added ? brand.green : brand.magenta;
            const prefix = part.added ? "+" : "-";
            return (
              <Box
                key={i}
                component="pre"
                sx={{
                  m: 0,
                  px: 1.5,
                  py: 0.25,
                  backgroundColor: bg,
                  color,
                  fontFamily: "inherit",
                  fontSize: "inherit",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {part.value
                  .replace(/\n$/, "")
                  .split("\n")
                  .map((line, li) => (
                    <span key={li}>
                      {li === 0 ? `${prefix} ` : `${prefix} `}
                      {line}
                      {li <
                        part.value.replace(/\n$/, "").split("\n").length -
                          1 && <br />}
                    </span>
                  ))}
              </Box>
            );
          })}
        </Box>
      )}
    </Box>
  );
}

// ── main component ────────────────────────────────────────────────────────────

interface Props {
  folderId: string;
}

export default function BriefingHistoryPanel({ folderId }: Props) {
  const queryClient = useQueryClient();
  // selected: up to 2 version IDs. First click = older, second = newer (for diff direction).
  const [selected, setSelected] = useState<string[]>([]);
  const [restoring, setRestoring] = useState<string | null>(null);

  // ── queries ──────────────────────────────────────────────────────────────

  const {
    data: history,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: qk.briefingHistory(folderId),
    queryFn: () => fetchBriefingHistory(folderId),
  });

  const v0Id = selected[0] ?? null;
  const v1Id = selected[1] ?? null;

  const { data: version0 } = useQuery({
    queryKey: qk.briefingVersion(folderId, v0Id ?? ""),
    queryFn: () => fetchBriefingVersion(folderId, v0Id!),
    enabled: v0Id != null && selected.length === 2,
  });

  const { data: version1 } = useQuery({
    queryKey: qk.briefingVersion(folderId, v1Id ?? ""),
    queryFn: () => fetchBriefingVersion(folderId, v1Id!),
    enabled: v1Id != null && selected.length === 2,
  });

  // ── handlers ──────────────────────────────────────────────────────────────

  function handleVersionClick(id: string) {
    setSelected((prev) => {
      if (prev.includes(id)) {
        // Deselect
        return prev.filter((x) => x !== id);
      }
      if (prev.length >= 2) {
        // Replace the oldest selection with the new one
        return [prev[1], id];
      }
      return [...prev, id];
    });
  }

  async function handleRestore(versionId: string) {
    setRestoring(versionId);
    try {
      await restoreBriefingVersion(folderId, versionId);
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: qk.briefingHistory(folderId),
        }),
        queryClient.invalidateQueries({
          queryKey: qk.briefing(folderId),
        }),
      ]);
    } finally {
      setRestoring(null);
    }
  }

  // ── loading / error states ────────────────────────────────────────────────

  if (isPending) {
    return (
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, p: 2 }}>
        <CircularProgress size={16} sx={{ color: brand.cyan }} />
        <Typography
          sx={{ fontFamily: fonts.mono, fontSize: 13, color: brand.muted }}
        >
          Loading history…
        </Typography>
      </Box>
    );
  }

  if (isError) {
    return (
      <Box
        data-testid="history-error"
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          p: 2,
          border: `1px solid ${brand.magenta}44`,
          borderRadius: 1,
          background: `${brand.magenta}0d`,
        }}
      >
        <ErrorOutlineIcon sx={{ fontSize: 18, color: brand.magenta }} />
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: 13,
            color: brand.text,
            flexGrow: 1,
          }}
        >
          Couldn't load history.
        </Typography>
        <Button
          variant="outlined"
          size="small"
          startIcon={<RefreshIcon />}
          onClick={() => void refetch()}
          sx={{
            fontFamily: fonts.mono,
            fontSize: 11,
            letterSpacing: "0.08em",
            borderColor: brand.magenta,
            color: brand.magenta,
            "&:hover": {
              borderColor: brand.magenta,
              backgroundColor: `${brand.magenta}12`,
            },
          }}
        >
          Retry
        </Button>
      </Box>
    );
  }

  // ── diff view ─────────────────────────────────────────────────────────────

  const showDiff =
    selected.length === 2 && version0 != null && version1 != null;

  // Collect all section keys from both versions
  const allKeys = showDiff
    ? Array.from(
        new Set([
          ...Object.keys(version0.sections),
          ...Object.keys(version1.sections),
        ])
      )
    : [];

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <Box sx={{ display: "flex", gap: 3, alignItems: "flex-start" }}>
      {/* Left: version timeline */}
      <Box sx={{ flex: "0 0 320px", minWidth: 0 }}>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.28em",
            textTransform: "uppercase",
            color: brand.muted,
            mb: 1.5,
          }}
        >
          Version history · {history?.length ?? 0}
        </Typography>

        {(!history || history.length === 0) && (
          <Typography
            sx={{ fontFamily: fonts.mono, fontSize: 13, color: brand.dim }}
          >
            No versions recorded yet.
          </Typography>
        )}

        <Stack spacing={1}>
          {(history ?? []).map((v) => {
            const isSelected = selected.includes(v.id);
            const borderColor = isSelected ? brand.cyan : brand.line;
            return (
              <CornerCard
                key={v.id}
                data-testid={`version-${v.id}`}
                color={isSelected ? brand.cyan : brand.violet2}
                onClick={() => handleVersionClick(v.id)}
                sx={{
                  p: 1.5,
                  cursor: "pointer",
                  border: `1px solid ${borderColor}`,
                  background: isSelected ? `${brand.cyan}0d` : brand.surface,
                  transition: "border-color 0.15s, background 0.15s",
                  "&:hover": {
                    borderColor: brand.cyan,
                    background: `${brand.cyan}08`,
                  },
                }}
              >
                {/* Top row: trigger badge + time */}
                <Stack
                  direction="row"
                  alignItems="center"
                  spacing={1}
                  sx={{ mb: 0.75 }}
                >
                  <Chip
                    label={v.trigger ?? "unknown"}
                    size="small"
                    sx={{
                      fontFamily: fonts.mono,
                      fontSize: 10,
                      height: 18,
                      letterSpacing: "0.06em",
                      backgroundColor: `${brand.violet2}22`,
                      color: brand.violet2,
                      border: `1px solid ${brand.violet2}44`,
                    }}
                  />
                  <Typography
                    sx={{
                      fontFamily: fonts.mono,
                      fontSize: 11,
                      color: brand.muted,
                      flexGrow: 1,
                    }}
                  >
                    {timeAgo(v.generated_at)}
                  </Typography>
                  {isSelected && (
                    <Box
                      component="span"
                      sx={{
                        fontFamily: fonts.mono,
                        fontSize: 10,
                        color: brand.cyan,
                        textShadow: `0 0 6px ${brand.cyan}`,
                      }}
                    >
                      ●
                    </Box>
                  )}
                </Stack>

                {/* Changed sections chips */}
                {v.changed_sections.length > 0 && (
                  <Stack
                    direction="row"
                    spacing={0.5}
                    sx={{ flexWrap: "wrap", mb: 0.75, gap: "4px" }}
                  >
                    {v.changed_sections.map((sec) => (
                      <Chip
                        key={sec}
                        label={sec}
                        size="small"
                        sx={{
                          fontFamily: fonts.mono,
                          fontSize: 9,
                          height: 16,
                          letterSpacing: "0.04em",
                          backgroundColor: `${brand.amber}18`,
                          color: brand.amber,
                          border: `1px solid ${brand.amber}33`,
                        }}
                      />
                    ))}
                  </Stack>
                )}

                {/* Restore button */}
                <Button
                  data-testid={`restore-${v.id}`}
                  variant="outlined"
                  size="small"
                  startIcon={
                    restoring === v.id ? (
                      <CircularProgress size={12} />
                    ) : (
                      <RestoreIcon />
                    )
                  }
                  disabled={restoring != null}
                  onClick={(e) => {
                    e.stopPropagation();
                    void handleRestore(v.id);
                  }}
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 10,
                    letterSpacing: "0.06em",
                    borderColor: `${brand.magenta}66`,
                    color: brand.magenta,
                    py: 0.25,
                    px: 1,
                    minHeight: 0,
                    "&:hover": {
                      borderColor: brand.magenta,
                      backgroundColor: `${brand.magenta}12`,
                    },
                    "&.Mui-disabled": {
                      borderColor: brand.line,
                      color: brand.muted,
                    },
                  }}
                >
                  {restoring === v.id ? "Restoring…" : "Restore"}
                </Button>
              </CornerCard>
            );
          })}
        </Stack>

        {selected.length > 0 && selected.length < 2 && (
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: 11,
              color: brand.muted,
              mt: 1.5,
            }}
          >
            Select one more version to compare.
          </Typography>
        )}
      </Box>

      {/* Right: diff panel (only when 2 selected and data loaded) */}
      {selected.length === 2 && (
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: "0.28em",
              textTransform: "uppercase",
              color: brand.muted,
              mb: 1.5,
            }}
          >
            Diff
          </Typography>

          {!version0 || !version1 ? (
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <CircularProgress size={14} sx={{ color: brand.cyan }} />
              <Typography
                sx={{
                  fontFamily: fonts.mono,
                  fontSize: 12,
                  color: brand.muted,
                }}
              >
                Loading versions…
              </Typography>
            </Box>
          ) : (
            <Box>
              {allKeys.map((key) => {
                const oldSec = version0.sections[key];
                const newSec = version1.sections[key];
                const oldText = serializeSection(oldSec?.content ?? null);
                const newText = serializeSection(newSec?.content ?? null);
                return (
                  <SectionDiff
                    key={key}
                    sectionKey={key}
                    oldText={oldText}
                    newText={newText}
                  />
                );
              })}
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}
