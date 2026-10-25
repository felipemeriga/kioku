import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { qk } from "../lib/queryKeys";
import {
  Alert,
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
import { messageFromError } from "./ToastProvider";
import { brand, fonts } from "../theme";
import { getFolderStatus, refreshFolder } from "../lib/api";
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
  const [requestError, setRequestError] = useState(false);
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

  // Poll until Mihari records completion (or the job times out).
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
  const latestError =
    (status?.index_refresh_started_at ?? "") >
    (status?.sections_refresh_started_at ?? "")
      ? status?.index_refresh_error
      : status?.sections_refresh_error;
  const message =
    note ||
    (anyRunning
      ? "Refresh requested. Waiting for Mihari to finish."
      : latestState === "failed"
      ? `Refresh failed. ${
          latestError || "Mihari did not report diagnostic details."
        } Retry when the issue is resolved.`
      : latestState === "timed-out"
      ? "Refresh timed out or was interrupted. Please retry."
      : latestState === "completed"
      ? "Refresh completed. Unchanged content keeps its original timestamp."
      : "");

  const start = async (target: "index" | "sections") => {
    if (anyRunning) return;
    setNote("");
    setRequestError(false);
    setNow(Date.now());
    setClicking(target);
    try {
      await refreshFolder(folderId, target);
      setNote("Refresh started…");
      await refetch(); // pull the server's started_at so the state persists
      setNote("");
    } catch (e) {
      const code = (e as { status?: number })?.status;
      if (code === 409) {
        await refetch();
        setNote("");
      } else {
        setRequestError(true);
        setNote(
          code === 503
            ? `Mihari unavailable. ${messageFromError(e, "Try again shortly.")}`
            : messageFromError(e, "Couldn’t start the refresh. Please retry.")
        );
      }
    } finally {
      setClicking(null); // server-derived running() takes over from here
    }
  };

  const attribution = (value: string | null | undefined): string | null => {
    if (!value) return null;
    if (
      [
        "watcher",
        "kioku-watcher",
        "cloud-watcher",
        "cloud_watcher",
        "mihari",
      ].includes(value.trim().toLowerCase())
    )
      return "by Mihari";
    if (value === "agent_mcp") return "Updated by an agent";
    if (/^[0-9a-f-]{36}$/i.test(value)) return "Updated in Kioku";
    return `by ${value}`;
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
      sub: attribution(status?.architecture_by),
      color: brand.cyan,
    },
    {
      icon: InfoOutlinedIcon,
      label: "Overview",
      at: status?.overview_at ?? null,
      sub: attribution(status?.overview_by),
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
            fontFamily: fonts.body,
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
            fontFamily: fonts.body,
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

  return (
    <Box className="repository-status">
      <Box
        sx={{
          border: `1px solid ${brand.line}`,
          borderRadius: 2,
          overflow: "hidden",
          bgcolor: brand.surface,
          mb: 3,
        }}
      >
        <Box
          className="status-header"
          sx={{ px: 3, py: 2.5, borderBottom: `1px solid ${brand.line}` }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 2,
              flexWrap: "wrap",
            }}
          >
            <Box sx={{ minWidth: 0, flex: "1 1 240px" }}>
              <Typography component="h2" sx={{ fontWeight: 600, fontSize: 18 }}>
                {anyRunning
                  ? "Refreshing repository context"
                  : requestError ||
                    latestState === "failed" ||
                    latestState === "timed-out"
                  ? "Refresh needs attention"
                  : "Repository context"}
              </Typography>
              <Typography sx={{ mt: 0.5, color: brand.muted, fontSize: 14 }}>
                Index and briefing timestamps reported by Mihari.
              </Typography>
            </Box>
            <Stack
              direction="row"
              spacing={1.5}
              sx={{ flexWrap: "wrap", rowGap: 1 }}
              data-testid="status-actions"
            >
              <Button
                variant="contained"
                disabled={isPending || anyRunning}
                onClick={() => start("index")}
                startIcon={
                  indexRunning ? (
                    <CircularProgress size={14} color="inherit" />
                  ) : (
                    <RefreshIcon />
                  )
                }
              >
                {indexRunning ? "Refreshing…" : "Refresh code index"}
              </Button>
              <Button
                variant="outlined"
                disabled={isPending || anyRunning}
                onClick={() => start("sections")}
                startIcon={
                  sectionsRunning ? (
                    <CircularProgress size={14} color="inherit" />
                  ) : (
                    <RefreshIcon />
                  )
                }
              >
                {sectionsRunning ? "Refreshing…" : "Refresh detail sections"}
              </Button>
            </Stack>
          </Box>
          {message && (
            <Alert
              role={
                requestError ||
                latestState === "failed" ||
                latestState === "timed-out"
                  ? "alert"
                  : "status"
              }
              severity={
                requestError || latestState === "failed"
                  ? "error"
                  : latestState === "timed-out"
                  ? "warning"
                  : "info"
              }
              sx={{ mt: 2, fontSize: 13, overflowWrap: "anywhere" }}
            >
              {message}
            </Alert>
          )}
        </Box>
        <Box className="status-list">
          {cards.map((c) => {
            const Icon = c.icon;
            const glyph = indexGlyph(c.at);
            return (
              <Box
                className="status-row"
                key={c.label}
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: 2,
                  px: 3,
                  py: 2.5,
                  borderBottom: `1px solid ${brand.line}`,
                  "&:last-child": { borderBottom: 0 },
                }}
              >
                <Icon sx={{ color: brand.cyan, fontSize: 22, flexShrink: 0 }} />
                <Box className="status-content" sx={{ minWidth: 0, flex: 1 }}>
                  <Typography sx={{ fontSize: 16, fontWeight: 500 }}>
                    {c.label}
                  </Typography>
                  {c.sub && (
                    <Typography
                      sx={{
                        color: brand.muted,
                        fontSize: 14,
                        mt: 0.5,
                        overflowWrap: "anywhere",
                      }}
                    >
                      {c.sub}
                    </Typography>
                  )}
                </Box>
                <Box
                  className="status-time"
                  sx={{ textAlign: "right", flexShrink: 0 }}
                >
                  {isPending ? (
                    <CircularProgress size={16} />
                  ) : (
                    <>
                      <Typography
                        sx={{
                          color: c.at ? brand.green : brand.muted,
                          fontSize: 13,
                        }}
                      >
                        {glyph.glyph} {c.at ? "Recorded" : "Not available"}
                      </Typography>
                      <Typography
                        sx={{ color: brand.muted, fontSize: 13, mt: 0.5 }}
                      >
                        {timeAgo(c.at)}
                      </Typography>
                    </>
                  )}
                </Box>
              </Box>
            );
          })}
        </Box>
      </Box>
    </Box>
  );
}
