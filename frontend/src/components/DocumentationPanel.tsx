import { useCallback, useEffect, useRef, useState } from "react";
import {
  Box,
  Paper,
  Typography,
  Collapse,
  IconButton,
  Chip,
} from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { brand, fonts } from "../theme";
import { fetchDocumentation, type RepoDocumentation } from "../lib/api";

function relTime(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** The "complete overview" deep architecture doc for a repo folder. Renders
 *  nothing for non-repo folders (the endpoint 400s) so it's safe to drop on any
 *  folder view. */
export default function DocumentationPanel({ folderId }: { folderId: string }) {
  const [doc, setDoc] = useState<RepoDocumentation | null>(null);
  const [loading, setLoading] = useState(true);
  const [hidden, setHidden] = useState(false);
  const [expanded, setExpanded] = useState(false);
  // Bumped on every load so a stale response from a previous folder/request
  // can't overwrite a newer one.
  const reqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++reqRef.current;
    setLoading(true);
    try {
      const res = await fetchDocumentation(folderId);
      if (seq !== reqRef.current) return;
      setDoc(res.documentation);
      setHidden(false);
    } catch {
      // Non-repo folder → 400. Render nothing.
      if (seq === reqRef.current) setHidden(true);
    } finally {
      if (seq === reqRef.current) setLoading(false);
    }
  }, [folderId]);

  // Initial load + reload when the folder changes.
  useEffect(() => {
    void load();
  }, [load]);

  // The briefing "Clear & regenerate" deletes the detailed doc too. Refetch on
  // that event so this panel drops the now-deleted doc instead of showing it
  // stale until a page reload.
  useEffect(() => {
    const handler = (e: Event) => {
      const cleared = (e as CustomEvent<{ folderId?: string }>).detail
        ?.folderId;
      if (!cleared || cleared === folderId) void load();
    };
    window.addEventListener("briefing-cleared", handler);
    return () => window.removeEventListener("briefing-cleared", handler);
  }, [folderId, load]);

  if (loading || hidden) return null;

  const cardSx = {
    p: 2.5,
    mb: 3,
    bgcolor: brand.surface,
    border: `1px solid ${brand.line}`,
    borderRadius: 3,
  } as const;

  const header = (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
      <DescriptionOutlinedIcon sx={{ fontSize: 20, color: brand.cyan }} />
      <Typography
        sx={{
          fontFamily: fonts.display,
          fontSize: "1.25rem",
          color: brand.text,
        }}
      >
        Detailed documentation
      </Typography>
    </Box>
  );

  if (!doc) {
    return (
      <Paper elevation={0} sx={cardSx}>
        {header}
        <Typography sx={{ color: brand.muted, mt: 1, fontSize: "0.9rem" }}>
          No detailed architecture doc yet. It's generated together with the
          repo summary — or, in a Claude Code session in this repo, say
          “generate the docs”.
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper elevation={0} sx={cardSx}>
      <Box
        onClick={() => setExpanded(!expanded)}
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
        }}
      >
        {header}
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <Chip
            label={relTime(doc.generated_at)}
            size="small"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.65rem",
              color: brand.muted,
              bgcolor: "transparent",
              border: `1px solid ${brand.line}`,
            }}
          />
          <IconButton size="small" sx={{ color: brand.muted }}>
            <ExpandMoreIcon
              sx={{
                transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
                transition: "transform 0.2s",
              }}
            />
          </IconButton>
        </Box>
      </Box>

      {doc.abstract && (
        <Typography
          sx={{
            color: brand.muted,
            mt: 1.5,
            fontSize: "0.92rem",
            lineHeight: 1.6,
            fontFamily: fonts.body,
          }}
        >
          {doc.abstract}
        </Typography>
      )}

      <Collapse in={expanded} timeout="auto">
        <Box
          sx={{
            mt: 2,
            pt: 2,
            borderTop: `1px solid ${brand.line}`,
            color: brand.text,
            fontFamily: fonts.body,
            fontSize: "0.9rem",
            lineHeight: 1.65,
            "& h1, & h2, & h3, & h4": {
              fontFamily: fonts.display,
              color: brand.text,
              mt: 2,
              mb: 1,
            },
            "& code": {
              fontFamily: fonts.mono,
              fontSize: "0.82em",
              bgcolor: brand.surface2,
              px: 0.5,
              borderRadius: 0.5,
            },
            "& pre": {
              bgcolor: brand.surface2,
              p: 1.5,
              borderRadius: 1,
              overflow: "auto",
            },
            "& a": { color: brand.cyan },
            "& table": { borderCollapse: "collapse" },
            "& th, & td": { border: `1px solid ${brand.line}`, px: 1, py: 0.5 },
          }}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {doc.content}
          </ReactMarkdown>
        </Box>
      </Collapse>

      {!expanded && (
        <Typography
          onClick={() => setExpanded(true)}
          sx={{
            mt: 1,
            fontFamily: fonts.mono,
            fontSize: "0.7rem",
            color: brand.cyan,
            cursor: "pointer",
          }}
        >
          ▸ Read the full document
        </Typography>
      )}
    </Paper>
  );
}
