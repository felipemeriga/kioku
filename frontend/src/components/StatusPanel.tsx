import { useCallback, useEffect, useRef, useState } from "react";
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
import RefreshIcon from "@mui/icons-material/Refresh";
import { brand, fonts } from "../theme";
import { getFolderStatus, refreshFolder, type FolderStatus } from "../lib/api";
import CornerCard from "./neo/CornerCard";

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

type Pending = {
  target: "index" | "sections";
  field: keyof FolderStatus;
  since: string | null;
} | null;

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
  const [status, setStatus] = useState<FolderStatus | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [note, setNote] = useState<string>("");
  const pollsRef = useRef(0);

  const load = useCallback(async () => {
    const s = await getFolderStatus(folderId);
    setStatus(s);
    return s;
  }, [folderId]);

  useEffect(() => {
    void (async () => {
      try {
        await load();
      } catch {
        setNote("Couldn't load status.");
      }
    })();
  }, [load]);

  // Poll while a refresh is pending until the watched field advances or we time out.
  useEffect(() => {
    if (!pending) return;
    pollsRef.current = 0;
    const id = setInterval(async () => {
      pollsRef.current += 1;
      let s: FolderStatus | null = null;
      try {
        s = await load();
      } catch {
        /* keep polling */
      }
      if (s && s[pending.field] !== pending.since) {
        setPending(null);
        setNote("Updated just now.");
        clearInterval(id);
      } else if (pollsRef.current >= 36) {
        setPending(null);
        setNote("Still running — check back in a bit.");
        clearInterval(id);
      }
    }, 5000);
    return () => clearInterval(id);
  }, [pending, load]);

  const start = async (
    target: "index" | "sections",
    field: keyof FolderStatus
  ) => {
    if (pending) return;
    setNote("");
    try {
      await refreshFolder(folderId, target);
      setPending({
        target,
        field,
        since: status ? (status[field] as string | null) : null,
      });
      setNote("Refresh started…");
    } catch (e) {
      const status409 = (e as { status?: number })?.status === 409;
      setNote(
        status409 ? "A refresh is already running." : "Watcher unavailable."
      );
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
              {/* Time ago */}
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
            pending?.target === "index" ? (
              <CircularProgress size={14} />
            ) : (
              <RefreshIcon />
            )
          }
          disabled={!!pending}
          onClick={() => start("index", "graph_at")}
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
          {pending?.target === "index" ? "Refreshing…" : "Refresh code index"}
        </Button>
        <Button
          variant="outlined"
          size="small"
          startIcon={
            pending?.target === "sections" ? (
              <CircularProgress size={14} />
            ) : (
              <RefreshIcon />
            )
          }
          disabled={!!pending}
          onClick={() => start("sections", "architecture_at")}
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
          {pending?.target === "sections"
            ? "Refreshing…"
            : "Refresh detail sections"}
        </Button>
        {note && (
          <Typography
            sx={{ fontFamily: fonts.mono, fontSize: 11, color: brand.muted }}
          >
            {note}
          </Typography>
        )}
      </Stack>
    </Box>
  );
}
