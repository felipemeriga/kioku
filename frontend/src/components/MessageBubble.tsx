import { Children, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Box, Typography, Chip, Tooltip, alpha } from "@mui/material";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, DebugTrace } from "../lib/api";
import InspectDialog from "./InspectDialog";
import CornerCard from "./neo/CornerCard";
import { brand, fonts } from "../theme";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  debug?: DebugTrace;
  citations?: Citation[];
  /** Open a cited document in the in-app viewer. */
  onOpenDocument?: (filename: string, folderId?: string | null) => void;
}

const CITE_RE = /\[(\d+)\]/g;

/** A short label for a source in the footer / tooltip. */
function citationLabel(c: Citation): string {
  if (c.source_type === "code") {
    const loc = c.line ? `${c.file ?? c.source}:${c.line}` : c.file ?? c.source;
    return c.symbol ? `${loc} — ${c.symbol}` : loc;
  }
  return c.source;
}

/** Citation numbers that actually appear in the answer text, ignoring any that
 * sit inside fenced or inline code (those are literal, not references). */
function citedNumbers(content: string): Set<number> {
  const prose = content.replace(/```[\s\S]*?```/g, "").replace(/`[^`]*`/g, "");
  const nums = new Set<number>();
  for (const m of prose.matchAll(CITE_RE)) nums.add(Number(m[1]));
  return nums;
}

/** Inline [N] chip — hover shows the source + excerpt, click opens it. */
function CitationChip({
  c,
  onClick,
}: {
  c: Citation;
  onClick: (c: Citation) => void;
}) {
  return (
    <Tooltip
      arrow
      title={
        <Box sx={{ maxWidth: 320 }}>
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.7rem",
              color: brand.cyan,
            }}
          >
            {citationLabel(c)}
          </Typography>
          {c.excerpt && (
            <Typography
              sx={{
                fontSize: "0.75rem",
                mt: 0.5,
                color: alpha("#ffffff", 0.8),
                whiteSpace: "pre-wrap",
              }}
            >
              {c.excerpt}
            </Typography>
          )}
        </Box>
      }
    >
      <Box
        component="span"
        role="button"
        tabIndex={0}
        data-testid="citation-chip"
        onClick={() => onClick(c)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") onClick(c);
        }}
        sx={{
          cursor: "pointer",
          mx: "1px",
          px: "4px",
          fontFamily: fonts.mono,
          fontSize: "0.72em",
          fontWeight: 600,
          lineHeight: 1,
          verticalAlign: "super",
          color: brand.cyan,
          borderRadius: "3px",
          border: `1px solid ${brand.cyan}55`,
          bgcolor: `${brand.cyan}12`,
          "&:hover": { bgcolor: `${brand.cyan}26` },
        }}
      >
        {c.number}
      </Box>
    </Tooltip>
  );
}

/** Replace [N] markers in a plain-text run with clickable chips. Unknown
 * numbers (not in `cited`) are left as literal text. */
function splitCitations(
  text: string,
  cited: Map<number, Citation>,
  onClick: (c: Citation) => void
): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(CITE_RE)) {
    const c = cited.get(Number(m[1]));
    if (!c) continue; // leave unknown [N] as literal text
    const idx = m.index ?? 0;
    if (idx > last) parts.push(text.slice(last, idx));
    parts.push(<CitationChip key={key++} c={c} onClick={onClick} />);
    last = idx + m[0].length;
  }
  if (last === 0) return text; // nothing replaced
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** Linkify direct string children only. Nested elements self-handle (each
 * text-bearing element is overridden too); `code`/`pre` are never overridden,
 * so [N] inside code stays literal. */
function renderWithCitations(
  children: ReactNode,
  cited: Map<number, Citation>,
  onClick: (c: Citation) => void
): ReactNode {
  return Children.map(children, (child) =>
    typeof child === "string" ? splitCitations(child, cited, onClick) : child
  );
}

export default function MessageBubble({
  role,
  content,
  debug,
  citations,
  onOpenDocument,
}: MessageBubbleProps) {
  const isUser = role === "user";
  const [inspectOpen, setInspectOpen] = useState(false);

  const handleCitationClick = useMemo(
    () => (c: Citation) => {
      if (c.source_type === "document") {
        if (onOpenDocument) onOpenDocument(c.source, c.folder_id);
        else if (c.url) window.open(c.url, "_blank", "noopener,noreferrer");
      } else if (c.url) {
        // Code source → open the GitHub blob deep link.
        window.open(c.url, "_blank", "noopener,noreferrer");
      }
      // Code with no URL: the hover popover already surfaces the excerpt.
    },
    [onOpenDocument]
  );

  // Markdown renderers: always wrap tables; when citations exist, also linkify
  // [N] in every text-bearing element (code/pre are left untouched).
  const mdComponents = useMemo<Components>(() => {
    const base: Components = {
      table: (props) => (
        <div className="md-table-wrap">
          <table {...props} />
        </div>
      ),
    };
    if (!citations || citations.length === 0) return base;
    const cited = new Map(citations.map((c) => [c.number, c] as const));
    const r = (children: ReactNode) =>
      renderWithCitations(children, cited, handleCitationClick);
    return {
      ...base,
      p: (props) => <p {...props}>{r(props.children)}</p>,
      li: (props) => <li {...props}>{r(props.children)}</li>,
      td: (props) => <td {...props}>{r(props.children)}</td>,
      th: (props) => <th {...props}>{r(props.children)}</th>,
      em: (props) => <em {...props}>{r(props.children)}</em>,
      strong: (props) => <strong {...props}>{r(props.children)}</strong>,
      h1: (props) => <h1 {...props}>{r(props.children)}</h1>,
      h2: (props) => <h2 {...props}>{r(props.children)}</h2>,
      h3: (props) => <h3 {...props}>{r(props.children)}</h3>,
      h4: (props) => <h4 {...props}>{r(props.children)}</h4>,
      h5: (props) => <h5 {...props}>{r(props.children)}</h5>,
      h6: (props) => <h6 {...props}>{r(props.children)}</h6>,
    };
  }, [citations, handleCitationClick]);

  // Sources footer: only the sources whose [N] actually appears in the answer.
  const footerSources = useMemo(() => {
    if (!citations || citations.length === 0) return [];
    const used = citedNumbers(content);
    return citations
      .filter((c) => used.has(c.number))
      .sort((a, b) => a.number - b.number);
  }, [citations, content]);

  return (
    <Box
      sx={{
        display: "flex",
        justifyContent: isUser ? "flex-end" : "flex-start",
        alignItems: "flex-start",
        gap: 1,
        mb: 2,
      }}
    >
      {!isUser && (
        <Box
          data-testid="assistant-avatar"
          sx={{
            width: 30,
            height: 30,
            flexShrink: 0,
            borderRadius: 1,
            border: `1px solid ${brand.cyan}66`,
            background: `${brand.cyan}14`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: brand.cyan,
            fontSize: 14,
            mt: 0.5,
          }}
        >
          ✦
        </Box>
      )}
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          alignItems: isUser ? "flex-end" : "flex-start",
          maxWidth: { xs: "100%", md: isUser ? "75%" : "100%" },
          width: isUser ? "auto" : "100%",
          minWidth: 0,
        }}
      >
        {isUser ? (
          /* ── User bubble ── right-aligned, magenta tint */
          <Box
            data-testid="user-message-surface"
            sx={{
              px: 2,
              py: 1.5,
              background: `${brand.magenta}18`,
              border: `1px solid ${brand.magenta}88`,
              borderRadius: "12px 12px 3px 12px",
            }}
          >
            <Typography
              sx={{
                fontSize: "1rem",
                // Preserve the user's own line breaks instead of collapsing
                // them into one run, and break long unbreakable tokens (URLs,
                // curl commands) so they wrap inside the bubble.
                whiteSpace: "pre-wrap",
                overflowWrap: "anywhere",
              }}
            >
              {content}
            </Typography>
          </Box>
        ) : (
          /* Assistant message surface. */
          <CornerCard
            data-testid="assistant-message-surface"
            color={brand.cyan}
            corners={2}
            sx={{
              px: { xs: 2, sm: 3 },
              py: 2.5,
              width: "100%",
              border: `1px solid ${brand.cyan}99`,
              bgcolor: brand.surface,
              borderRadius: 2,
            }}
          >
            <Box
              sx={{
                "& p": { m: 0, mb: 1, "&:last-child": { mb: 0 } },
                "& ul, & ol": { my: 0.5, pl: 2.5 },
                "& li": { mb: 0.25 },
                "& pre": {
                  overflow: "auto",
                  bgcolor: alpha("#000000", 0.3),
                  p: 1.5,
                  borderRadius: 2,
                  my: 1,
                },
                "& code": {
                  fontSize: "0.85rem",
                  fontFamily: fonts.mono,
                },
                "& a": {
                  color: brand.cyan,
                  textDecoration: "none",
                  "&:hover": { textDecoration: "underline" },
                },
                // GFM tables (enabled via remark-gfm): compact, scrollable
                // container so a wide table doesn't blow out the bubble.
                "& .md-table-wrap": {
                  overflowX: "auto",
                  my: 1,
                  border: `1px solid ${alpha("#ffffff", 0.1)}`,
                  borderRadius: 1.5,
                },
                "& table": {
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "0.85rem",
                },
                "& thead": {
                  bgcolor: alpha(brand.magenta, 0.12),
                },
                "& th, & td": {
                  px: 1.25,
                  py: 0.75,
                  borderBottom: `1px solid ${alpha("#ffffff", 0.08)}`,
                  textAlign: "left",
                  verticalAlign: "top",
                },
                "& th": { fontWeight: 600, color: alpha("#ffffff", 0.9) },
                "& tbody tr:last-child td": { borderBottom: 0 },
                "& blockquote": {
                  m: 0,
                  my: 1,
                  pl: 1.5,
                  borderLeft: `3px solid ${alpha(brand.magenta, 0.5)}`,
                  color: alpha("#ffffff", 0.75),
                },
                fontSize: "1rem",
                lineHeight: 1.75,
                // Break long unbreakable tokens (bare URLs, inline code) so
                // they wrap instead of overflowing the bubble. Code blocks
                // keep their own horizontal scroll via the `& pre` rule above.
                overflowWrap: "anywhere",
              }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={mdComponents}
              >
                {content}
              </ReactMarkdown>
            </Box>
          </CornerCard>
        )}
        {!isUser && footerSources.length > 0 && (
          <Box
            data-testid="citation-sources"
            sx={{
              mt: 1,
              width: "100%",
              pt: 1,
              borderTop: `1px solid ${brand.cyan}22`,
            }}
          >
            <Typography
              sx={{
                fontFamily: fonts.mono,
                fontSize: "0.6rem",
                letterSpacing: "0.2em",
                color: brand.muted,
                mb: 0.5,
              }}
            >
              SOURCES
            </Typography>
            {footerSources.map((c) => (
              <Box
                key={c.number}
                role="button"
                tabIndex={0}
                data-testid="citation-source"
                onClick={() => handleCitationClick(c)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ")
                    handleCitationClick(c);
                }}
                sx={{
                  display: "flex",
                  gap: 0.75,
                  alignItems: "baseline",
                  cursor: "pointer",
                  py: 0.25,
                  fontFamily: fonts.mono,
                  fontSize: "0.75rem",
                  color: alpha("#ffffff", 0.75),
                  "&:hover": { color: brand.cyan },
                }}
              >
                <Box component="span" sx={{ color: brand.cyan }}>
                  [{c.number}]
                </Box>
                <Box
                  component="span"
                  sx={{ overflowWrap: "anywhere", minWidth: 0 }}
                >
                  {citationLabel(c)}
                </Box>
              </Box>
            ))}
          </Box>
        )}
        {!isUser && debug && (
          <Chip
            label="⌕ Inspect"
            size="small"
            onClick={() => setInspectOpen(true)}
            sx={{
              mt: 0.75,
              cursor: "pointer",
              height: 28,
              fontFamily: fonts.mono,
              fontSize: "0.75rem",
              bgcolor: `${brand.cyan}10`,
              color: brand.cyan,
              border: `1px solid ${brand.cyan}66`,
              borderRadius: "3px",
              "& .MuiChip-label": { px: 1.25 },
              "&:hover": { bgcolor: `${brand.cyan}20` },
            }}
          />
        )}
      </Box>
      {!isUser && debug && (
        <InspectDialog
          open={inspectOpen}
          onClose={() => setInspectOpen(false)}
          trace={debug}
        />
      )}
    </Box>
  );
}
