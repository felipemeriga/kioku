import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { qk } from "../lib/queryKeys";
import {
  Box,
  Stack,
  Typography,
  Button,
  CircularProgress,
} from "@mui/material";
import HistoryOutlinedIcon from "@mui/icons-material/HistoryOutlined";
import AccountTreeOutlinedIcon from "@mui/icons-material/AccountTreeOutlined";
import CodeIcon from "@mui/icons-material/Code";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutline";
import RefreshIcon from "@mui/icons-material/Refresh";
import { brand, fonts } from "../theme";
import { getFolderStatus, refreshFolder } from "../lib/api";
import CornerCard from "./neo/CornerCard";
import { refreshState } from "../lib/refreshState";

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

/** Maps a timeAgo string to a simple status glyph + color for the index-status cards. */
function indexGlyph(at: string | null): { glyph: string; color: string } {
  if (!at) return { glyph: "○", color: brand.muted };
  const diff = Date.now() - new Date(at).getTime();
  const h = diff / 3600000;
  if (h < 1) return { glyph: "●", color: brand.green };
  if (h < 24) return { glyph: "◐", color: brand.cyan };
  return { glyph: "○", color: brand.muted };
}

export default function StatusPanel({ folderId }: { folderId: string }) {
  const [note, setNote] = useState<string>("");
  const [now, setNow] = useState(Date.now);
  // Optimistic flag for the brief moment between the click and the refetch that
  // pulls the server's refresh-started timestamp.
  const [clicking, setClicking] = useState<null | "index" | "sections">(null);

  // Initial status read is cached (instant on revisit, background-refreshes).
  // isPending is only true on the very first load (no cache) — used to show a
  // loading state instead of "never".
  const {
    data: status,
    isPending,
    isError,
    refetch,
  } = useQuery({
    queryKey: qk.folderStatus(folderId),
    queryFn: () => getFolderStatus(folderId),
  });

  const indexState = refreshState(
    status?.index_refresh_started_at,
    status?.index_refresh_finished_at,
    status?.index_refresh_error,
    now
  );
  const sectionsState = refreshState(
    status?.sections_refresh_started_at,
    status?.sections_refresh_finished_at,
    status?.sections_refresh_error,
    now
  );
  const indexRunning = clicking === "index" || indexState === "running";
  const sectionsRunning =
    clicking === "sections" || sectionsState === "running";
  const anyRunning = indexRunning || sectionsRunning;

  // Poll until the watcher records completion (or the job times out).
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => {
      // A clock tick must rerender even when polling returns identical data.
      setNow(Date.now());
      void refetch();
    }, 5000);
    return () => clearInterval(id);
  }, [anyRunning, refetch]);

  const latestState =
    (status?.index_refresh_started_at ?? "") >
    (status?.sections_refresh_started_at ?? "")
      ? indexState
      : sectionsState;
  const message =
    note ||
    (anyRunning
      ? note
      : latestState === "failed"
      ? "Refresh failed. Check watcher logs and retry."
      : latestState === "timed-out"
      ? "Refresh timed out or was interrupted. Please retry."
      : latestState === "completed"
      ? "Refresh completed. Unchanged content keeps its original timestamp."
      : "");

  const start = async (target: "index" | "sections") => {
    if (anyRunning) return;
    setNote("");
    setNow(Date.now());
    setClicking(target);
    try {
      await refreshFolder(folderId, target);
      setNote("Refresh started…");
      await refetch(); // pull the server's started_at so the state persists
      setNote("");
    } catch (e) {
      const is409 = (e as { status?: number })?.status === 409;
      setNote(is409 ? "A refresh is already running." : "Watcher unavailable.");
    } finally {
      setClicking(null); // server-derived running() takes over from here
    }
  };

  const cards = [
    {
      icon: HistoryOutlinedIcon,
      label: "Git updates",
      at: status?.git_updates_at ?? null,
      sub: status?.head_sha ? `main @ ${status.head_sha.slice(0, 7)}` : null,
      color: brand.cyan,
    },
    {
      icon: AccountTreeOutlinedIcon,
      label: "Graph",
      at: status?.graph_at ?? null,
      sub:
        status?.graph_nodes != null
          ? `${status.graph_nodes} symbols · ${status.graph_edges} edges`
          : null,
      color: brand.magenta,
    },
    {
      icon: CodeIcon,
      label: "Semantic code",
      at: status?.semantic_code_at ?? null,
      sub: "voyage-code-3",
      color: brand.violet2,
    },
    {
      icon: InfoOutlinedIcon,
      label: "Architecture",
      at: status?.architecture_at ?? null,
      sub: status?.architecture_by ? `by ${status.architecture_by}` : null,
      color: brand.cyan,
    },
    {
      icon: InfoOutlinedIcon,
      label: "Overview",
      at: status?.overview_at ?? null,
      sub: status?.overview_by ? `by ${status.overview_by}` : null,
      color: brand.magenta,
    },
    {
      icon: DescriptionOutlinedIcon,
      label: "Detailed docs",
      at: status?.detailed_doc_at ?? null,
      sub: null,
      color: brand.violet2,
    },
  ];

  // First load failed with nothing cached to fall back on — show an explicit
  // error + retry instead of a grid of misleading "never" cards. A background
  // refetch failure with cached data still shows the (stale) cards.
  if (isError && !status) {
    return (
      <Box
        data-testid="status-error"
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
          Couldn't load status.
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

  return (
    <Box>
      <Stack direction="row" spacing={1.5} sx={{ flexWrap: "wrap", mb: 2 }}>
        {cards.map((c) => {
          const Icon = c.icon;
          const glyph = indexGlyph(c.at);
          return (
            <CornerCard
              key={c.label}
              color={c.color}
              sx={{
                flex: "1 1 180px",
                minWidth: 160,
                p: 1.5,
              }}
            >
              {/* Label row */}
              <Stack
                direction="row"
                spacing={0.75}
                alignItems="center"
                sx={{ mb: 0.5 }}
              >
                <Icon sx={{ fontSize: 14, color: c.color }} />
                <Typography
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 10,
                    fontWeight: 600,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: brand.muted,
                  }}
                >
                  {c.label}
                </Typography>
                <Box sx={{ flexGrow: 1 }} />
                {/* Status glyph — derived from freshness */}
                <Box
                  component="span"
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 11,
                    color: glyph.color,
                    textShadow:
                      glyph.color !== brand.muted
                        ? `0 0 6px ${glyph.color}`
                        : "none",
                  }}
                >
                  {glyph.glyph}
                </Box>
              </Stack>
              {/* Time ago — show a spinner until the first fetch lands, so the
                  cards don't flash "never" before the values arrive. */}
              {isPending ? (
                <Box sx={{ height: 21, display: "flex", alignItems: "center" }}>
                  <CircularProgress size={13} sx={{ color: brand.muted }} />
                </Box>
              ) : (
                <Typography
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 14,
                    color: brand.text,
                    fontWeight: 500,
                  }}
                >
                  {timeAgo(c.at)}
                </Typography>
              )}
              {/* Sub-label */}
              {c.sub && (
                <Typography
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 10,
                    color: brand.dim,
                    mt: 0.25,
                  }}
                >
                  {c.sub}
                </Typography>
              )}
            </CornerCard>
          );
        })}
      </Stack>

      <Stack
        direction="row"
        spacing={1.5}
        alignItems="center"
        sx={{ flexWrap: "wrap" }}
      >
        <Button
          variant="outlined"
          size="small"
          startIcon={
            indexRunning ? <CircularProgress size={14} /> : <RefreshIcon />
          }
          disabled={anyRunning}
          onClick={() => start("index")}
          sx={{
            fontFamily: fonts.mono,
            fontSize: 11,
            letterSpacing: "0.08em",
            borderColor: brand.cyan,
            color: brand.cyan,
            "&:hover": {
              borderColor: brand.cyan,
              backgroundColor: `${brand.cyan}12`,
              boxShadow: `0 0 12px ${brand.cyan}44`,
            },
            "&.Mui-disabled": {
              borderColor: brand.line,
              color: brand.muted,
            },
          }}
        >
          {indexRunning ? "Refreshing…" : "Refresh code index"}
        </Button>
        <Button
          variant="outlined"
          size="small"
          startIcon={
            sectionsRunning ? <CircularProgress size={14} /> : <RefreshIcon />
          }
          disabled={anyRunning}
          onClick={() => start("sections")}
          sx={{
            fontFamily: fonts.mono,
            fontSize: 11,
            letterSpacing: "0.08em",
            borderColor: brand.magenta,
            color: brand.magenta,
            "&:hover": {
              borderColor: brand.magenta,
              backgroundColor: `${brand.magenta}12`,
              boxShadow: `0 0 12px ${brand.magenta}44`,
            },
            "&.Mui-disabled": {
              borderColor: brand.line,
              color: brand.muted,
            },
          }}
        >
          {sectionsRunning ? "Refreshing…" : "Refresh detail sections"}
        </Button>
        {message && (
          <Typography
            sx={{ fontFamily: fonts.mono, fontSize: 11, color: brand.muted }}
          >
            {message}
          </Typography>
        )}
      </Stack>
    </Box>
  );
}
