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
import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
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
import { useToast } from "./ToastProvider";

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
  return (
    <Box
      data-testid={`diff-${sectionKey}`}
      sx={{ mb: 3, pb: 3, borderBottom: `1px solid ${brand.line}` }}
    >
      <Typography
        component="h3"
        sx={{
          fontSize: 17,
          fontWeight: 600,
          textTransform: "capitalize",
          mb: 1.5,
        }}
      >
        {sectionKey.replaceAll("_", " ")}
      </Typography>
      {parts
        .filter((part) => part.added || part.removed)
        .map((part, index) => (
          <Box
            key={index}
            sx={{
              mt: 1.5,
              p: "13px 16px",
              borderLeft: `2px solid ${
                part.added ? brand.green : brand.magenta
              }`,
              bgcolor: part.added ? `${brand.green}09` : `${brand.magenta}09`,
            }}
          >
            <Typography sx={{ fontSize: 12, color: brand.muted, mb: 1 }}>
              {part.added ? "Current" : "Previous"}
            </Typography>
            <Box
              component="pre"
              sx={{
                m: 0,
                fontFamily: fonts.body,
                fontSize: 14,
                lineHeight: 1.7,
                whiteSpace: "pre-wrap",
                overflowWrap: "anywhere",
                color: brand.text,
              }}
            >
              {part.value
                .replace(/\n$/, "")
                .split("\n")
                .map((line, index, lines) => (
                  <span key={index}>
                    {`${part.added ? "+" : "-"} ${line}`}
                    {index < lines.length - 1 && <br />}
                  </span>
                ))}
            </Box>
          </Box>
        ))}
    </Box>
  );
}

// ── main component ────────────────────────────────────────────────────────────

interface Props {
  folderId: string;
}

export default function BriefingHistoryPanel({ folderId }: Props) {
  const queryClient = useQueryClient();
  const toast = useToast();
  // selected: up to 2 version IDs, in click order. Diff direction is resolved
  // chronologically (by generated_at), NOT by click order — see below.
  const [manualSelection, setSelected] = useState<string[]>([]);
  const [restoring, setRestoring] = useState<string | null>(null);

  // ── queries ──────────────────────────────────────────────────────────────

  const {
    data: historyPages,
    isPending,
    isError,
    refetch,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: qk.briefingHistory(folderId),
    queryFn: ({ pageParam }) => fetchBriefingHistory(folderId, 50, pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) =>
      lastPage.length === 50 ? pages.length * 50 : undefined,
  });
  const history = historyPages?.pages.flat();
  const selected = manualSelection.length
    ? manualSelection
    : (history ?? []).slice(0, 2).map((v) => v.id);

  const v0Id = selected[0] ?? null;
  const v1Id = selected[1] ?? null;

  const firstVersion = useQuery({
    queryKey: qk.briefingVersion(folderId, v0Id ?? ""),
    queryFn: () => fetchBriefingVersion(folderId, v0Id!),
    enabled: v0Id != null,
  });

  const secondVersion = useQuery({
    queryKey: qk.briefingVersion(folderId, v1Id ?? ""),
    queryFn: () => fetchBriefingVersion(folderId, v1Id!),
    enabled: v1Id != null && selected.length === 2,
  });
  const version0 = firstVersion.data;
  const version1 = secondVersion.data;
  const versionError =
    firstVersion.isError || (selected.length === 2 && secondVersion.isError);

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
      toast.showSuccess("Briefing restored.");
    } catch (error) {
      toast.showError(error, "Couldn't restore this version.");
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
            fontSize: 13,
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

  // Resolve diff direction CHRONOLOGICALLY, not by click order. The timeline
  // renders newest-first, so clicking top-to-bottom selects newer→older; using
  // click order as old→new would swap additions/removals. Look each selected id
  // up in `history` (already fetched) and make the OLDER version the baseline
  // (oldText) and the NEWER version the additions (newText).
  const ts = (id: string | null): number => {
    const at = history?.find((h) => h.id === id)?.generated_at ?? null;
    return at ? new Date(at).getTime() : 0;
  };
  const [olderVersion, newerVersion] = showDiff
    ? ts(v0Id) <= ts(v1Id)
      ? [version0, version1]
      : [version1, version0]
    : [undefined, undefined];

  // Collect all section keys from both versions
  const allKeys =
    showDiff && olderVersion && newerVersion
      ? Array.from(
          new Set([
            ...Object.keys(olderVersion.sections),
            ...Object.keys(newerVersion.sections),
          ])
        )
      : [];

  const changedKeys = allKeys.filter(
    (key) =>
      serializeSection(olderVersion?.sections[key]?.content ?? null) !==
      serializeSection(newerVersion?.sections[key]?.content ?? null)
  );
  const unchangedKeys = allKeys.filter((key) => !changedKeys.includes(key));

  // The latest real pair is shown initially; clicking a row inspects it.
  return (
    <Box className="history-panel">
      <Typography
        sx={{ fontSize: 13, lineHeight: 1.55, color: brand.muted, mb: "20px" }}
      >
        Compare two briefing versions, or inspect a previous version before
        restoring it.
      </Typography>
      <Box
        className="history-layout"
        sx={{
          display: "grid",
          gridTemplateColumns: "260px minmax(0,1fr)",
          gap: "22px",
          alignItems: "start",
        }}
      >
        <Box>
          <Stack spacing={1.25}>
            {(history ?? []).map((v) => (
              <Box
                component="button"
                key={v.id}
                data-testid={`version-${v.id}`}
                onClick={() => handleVersionClick(v.id)}
                sx={{
                  width: "100%",
                  textAlign: "left",
                  fontFamily: fonts.body,
                  p: "17px 18px",
                  border: `1px solid ${
                    (manualSelection.length
                      ? manualSelection
                      : selected.slice(0, 1)
                    ).includes(v.id)
                      ? brand.cyan
                      : brand.line
                  }`,
                  borderRadius: "5px",
                  background: brand.surface,
                  color: brand.text,
                  cursor: "pointer",
                  "&:hover": { borderColor: brand.cyan },
                }}
              >
                <Typography
                  component="span"
                  sx={{ display: "block", fontSize: 14, fontWeight: 500 }}
                >
                  {v.generated_at
                    ? new Date(v.generated_at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : "Undated version"}
                </Typography>
                <Typography
                  component="span"
                  sx={{
                    display: "block",
                    fontSize: 12,
                    color: brand.muted,
                    my: 1,
                  }}
                >
                  {v.changed_sections?.length
                    ? v.changed_sections.join(", ")
                    : "All sections"}
                </Typography>
                <Chip
                  label={v.trigger ?? "unknown"}
                  size="small"
                  variant="outlined"
                  sx={{
                    height: 22,
                    fontSize: 10,
                    borderRadius: "3px",
                    color: brand.cyan,
                    borderColor: `${brand.cyan}44`,
                  }}
                />
              </Box>
            ))}
          </Stack>
          {!history?.length && (
            <Typography color="text.secondary">
              No versions recorded yet.
            </Typography>
          )}
          {hasNextPage && (
            <Button
              disabled={isFetchingNextPage}
              onClick={() => void fetchNextPage()}
            >
              {isFetchingNextPage ? "Loading…" : "Load older versions"}
            </Button>
          )}
        </Box>
        {selected.length > 0 && (
          <Box
            sx={{
              border: `1px solid ${brand.line}`,
              borderRadius: "8px",
              bgcolor: brand.surface,
              overflow: "hidden",
              minWidth: 0,
            }}
          >
            <Box
              sx={{
                p: "20px 24px",
                borderBottom: `1px solid ${brand.line}`,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 2,
                flexWrap: "wrap",
              }}
            >
              <Box>
                <Typography
                  component="h2"
                  sx={{ fontSize: 21, fontWeight: 600 }}
                >
                  {manualSelection.length === 0
                    ? "Latest changes"
                    : selected.length === 2
                    ? "Diff"
                    : "Version details"}
                </Typography>
                <Typography sx={{ fontSize: 13, color: brand.muted, mt: 0.5 }}>
                  {selected.length === 2
                    ? "Selected versions, compared chronologically"
                    : `${timeAgo(
                        history?.find((v) => v.id === v0Id)?.generated_at ??
                          null
                      )}`}
                </Typography>
              </Box>
              <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
                {(history?.length ?? 0) > 1 && (
                  <Button
                    variant="outlined"
                    onClick={() =>
                      setSelected((history ?? []).slice(0, 2).map((v) => v.id))
                    }
                  >
                    Compare versions
                  </Button>
                )}
                {v0Id && manualSelection.length > 0 && (
                  <Button
                    data-testid={`restore-${v0Id}`}
                    variant="outlined"
                    disabled={restoring != null}
                    startIcon={
                      restoring ? (
                        <CircularProgress size={12} />
                      ) : (
                        <RestoreIcon />
                      )
                    }
                    onClick={() => void handleRestore(v0Id)}
                  >
                    {restoring ? "Restoring…" : "Restore version"}
                  </Button>
                )}
              </Box>
            </Box>
            <Box className="history-details" sx={{ p: 3 }}>
              {versionError ? (
                <Box role="alert">
                  <Typography>Couldn't load this version.</Typography>
                  <Button
                    onClick={() => {
                      void firstVersion.refetch();
                      if (selected.length === 2) void secondVersion.refetch();
                    }}
                  >
                    Retry
                  </Button>
                </Box>
              ) : selected.length === 1 && version0 ? (
                <Box data-testid="version-details">
                  {Object.entries(version0.sections).map(([key, section]) => (
                    <Box key={key} sx={{ mb: 3 }}>
                      <Typography
                        component="h3"
                        sx={{
                          fontSize: 17,
                          fontWeight: 600,
                          textTransform: "capitalize",
                          mb: 1.5,
                        }}
                      >
                        {key.replaceAll("_", " ")}
                      </Typography>
                      <Box
                        sx={{
                          whiteSpace: "pre-wrap",
                          overflowWrap: "anywhere",
                          fontSize: 16,
                          lineHeight: 1.75,
                          color: brand.muted,
                        }}
                      >
                        {serializeSection(section.content)}
                      </Box>
                    </Box>
                  ))}
                </Box>
              ) : !olderVersion || !newerVersion ? (
                <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
                  <CircularProgress size={14} />
                  <Typography color="text.secondary">
                    Loading versions…
                  </Typography>
                </Box>
              ) : (
                <Box>
                  {changedKeys.map((key) => (
                    <SectionDiff
                      key={key}
                      sectionKey={key}
                      oldText={serializeSection(
                        olderVersion.sections[key]?.content ?? null
                      )}
                      newText={serializeSection(
                        newerVersion.sections[key]?.content ?? null
                      )}
                    />
                  ))}
                  {unchangedKeys.length > 0 && (
                    <Box
                      component="details"
                      sx={{
                        borderTop: `1px solid ${brand.line}`,
                        pt: 2.5,
                        mt: 2.5,
                      }}
                    >
                      <Box
                        component="summary"
                        sx={{
                          fontSize: 16,
                          cursor: "pointer",
                          color: brand.text,
                        }}
                      >
                        {unchangedKeys.length} unchanged{" "}
                        {unchangedKeys.length === 1 ? "section" : "sections"}
                      </Box>
                      {unchangedKeys.map((key) => (
                        <Box key={key} sx={{ pt: 2 }}>
                          <Typography
                            component="h3"
                            sx={{
                              fontSize: 16,
                              fontWeight: 600,
                              textTransform: "capitalize",
                            }}
                          >
                            {key.replaceAll("_", " ")}
                          </Typography>
                          <Box
                            sx={{
                              fontSize: 14,
                              lineHeight: 1.7,
                              color: brand.muted,
                              whiteSpace: "pre-wrap",
                              mt: 1,
                            }}
                          >
                            {serializeSection(
                              newerVersion?.sections[key]?.content ?? null
                            )}
                          </Box>
                        </Box>
                      ))}
                    </Box>
                  )}
                </Box>
              )}
            </Box>
          </Box>
        )}
      </Box>
    </Box>
  );
}
