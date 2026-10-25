import { Children, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Box,
  Button,
  Typography,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  alpha,
} from "@mui/material";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, DebugTrace } from "../lib/api";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { useToast } from "./ToastProvider";
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

/** Labels keep real source identity; missing metadata is never treated as a filename. */
function citationLabel(c: Citation): string {
  const source = c.source?.trim() ?? "";
  if (c.source_type === "code") {
    const file = c.file?.trim() || source;
    const loc = c.line ? `${file}:${c.line}` : file;
    return (c.symbol ? `${loc} — ${c.symbol}` : loc) || "Retrieved code source";
  }
  return source && !/^(unknown|\[unknown\])$/i.test(source)
    ? source
    : "Retrieved source";
}

/** Source previews are short prose, never raw fenced Markdown or a wall of code. */
function citationPreview(value: string): string {
  const text = value
    .replace(/(^|\n)[ \t]*(?:`{3,}|~{3,})[\w+-]*[ \t]*(?:\r?\n|$)/g, "$1")
    .replace(/`+|~{3,}/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > 220 ? `${text.slice(0, 219).trimEnd()}…` : text;
}

/** Citation numbers that actually appear in the answer text, ignoring any that
 * sit inside fenced or inline code (those are literal, not references). */
function citedNumbers(content: string): Set<number> {
  const prose = content.replace(/```[\s\S]*?```/g, "").replace(/`[^`]*`/g, "");
  const nums = new Set<number>();
  for (const m of prose.matchAll(CITE_RE)) nums.add(Number(m[1]));
  return nums;
}

/** Hover/focus is a bounded preview; activation follows the real source contract. */
function CitationChip({
  c,
  onClick,
}: {
  c: Citation;
  onClick: (c: Citation) => void;
}) {
  const [open, setOpen] = useState(false);
  const activate = () => {
    setOpen(false);
    onClick(c);
  };
  return (
    <Tooltip
      arrow
      describeChild
      placement="top"
      disableInteractive
      disableTouchListener
      open={open}
      onOpen={() => setOpen(true)}
      onClose={() => setOpen(false)}
      slotProps={{
        tooltip: {
          sx: {
            maxWidth: "min(360px, calc(100vw - 32px))",
            boxSizing: "border-box",
            maxHeight: "min(240px, calc(100dvh - 32px))",
            overflow: "hidden",
            p: "12px 14px",
            color: brand.text,
            bgcolor: brand.raised,
            border: `1px solid ${brand.lineGlow}`,
            overflowWrap: "anywhere",
            wordBreak: "break-word",
            fontSize: 13,
            lineHeight: 1.55,
          },
        },
        popper: {
          disablePortal: false,
          modifiers: [
            { name: "offset", options: { offset: [0, 8] } },
            {
              name: "flip",
              options: {
                rootBoundary: "viewport",
                padding: 16,
                fallbackPlacements: [
                  "top-start",
                  "top-end",
                  "bottom-start",
                  "bottom-end",
                ],
              },
            },
            {
              name: "preventOverflow",
              options: {
                rootBoundary: "viewport",
                padding: 16,
                altAxis: true,
                tether: false,
              },
            },
          ],
        },
      }}
      title={
        <Box>
          <Typography
            component="span"
            sx={{
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 2,
              overflow: "hidden",
              overflowWrap: "anywhere",
              fontSize: 13,
              fontWeight: 600,
              lineHeight: 1.45,
              color: brand.cyan,
            }}
          >
            {citationLabel(c)}
          </Typography>
          <Typography
            component="span"
            sx={{ display: "block", fontSize: 11, color: brand.muted, mt: 0.5 }}
          >
            {c.source_type === "code" ? "Code" : "Document"}
          </Typography>
          {c.excerpt && (
            <Typography
              component="span"
              sx={{
                display: "block",
                fontSize: 13,
                lineHeight: 1.55,
                color: brand.text,
                mt: 1,
                whiteSpace: "normal",
                overflowWrap: "anywhere",
              }}
            >
              {citationPreview(c.excerpt)}
            </Typography>
          )}
        </Box>
      }
    >
      <Box
        component="button"
        type="button"
        data-testid="citation-chip"
        aria-label={`Open source ${c.number}: ${citationLabel(c)}`}
        onClick={activate}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate();
          } else if (event.key === "Escape") setOpen(false);
        }}
        sx={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          minWidth: 20,
          height: 20,
          cursor: "pointer",
          mx: "2px",
          px: "4px",
          fontFamily: fonts.mono,
          fontSize: 12,
          fontWeight: 600,
          lineHeight: 1,
          verticalAlign: "baseline",
          position: "relative",
          top: "-0.1em",
          color: brand.cyan,
          borderRadius: "4px",
          border: `1px solid ${brand.cyan}77`,
          bgcolor: `${brand.cyan}12`,
          touchAction: "manipulation",
          "&:hover": { bgcolor: `${brand.cyan}26` },
          "&:focus-visible": {
            outline: `2px solid ${brand.cyan}`,
            outlineOffset: 3,
          },
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
  const toast = useToast();
  const isUser = role === "user";
  const [inspectOpen, setInspectOpen] = useState(false);
  const [excerptSource, setExcerptSource] = useState<Citation | null>(null);

  const handleCitationClick = useMemo(
    () => (c: Citation) => {
      if (c.source_type === "document") {
        const filename = c.source?.trim() ?? "";
        if (!filename || /^(unknown|\[unknown\])$/i.test(filename)) {
          setExcerptSource(c);
        } else if (onOpenDocument) onOpenDocument(filename, c.folder_id);
        else if (c.url) window.open(c.url, "_blank", "noopener,noreferrer");
        else setExcerptSource(c);
      } else if (c.url) {
        window.open(c.url, "_blank", "noopener,noreferrer");
      } else {
        setExcerptSource(c);
      }
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
      className="message-bubble"
      sx={{
        minWidth: 0,
        maxWidth: "100%",
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
              minWidth: 0,
              maxWidth: "100%",
              boxSizing: "border-box",
              border: `1px solid ${brand.cyan}99`,
              bgcolor: brand.surface,
              borderRadius: 2,
            }}
          >
            <Typography sx={{ fontSize: 13, color: brand.cyan, mb: 1.5 }}>
              Kioku
            </Typography>
            <Box
              sx={{
                "& p": { m: 0, mb: 1, "&:last-child": { mb: 0 } },
                "& ul, & ol": { my: 0.5, pl: 2.5 },
                "& li": { mb: 0.25 },
                minWidth: 0,
                width: "100%",
                maxWidth: "100%",
                "& pre": {
                  display: "block",
                  minWidth: 0,
                  maxWidth: "100%",
                  boxSizing: "border-box",
                  overflowX: "auto",
                  whiteSpace: "pre",
                  overflowWrap: "normal",
                  wordBreak: "normal",
                  bgcolor: alpha("#000000", 0.3),
                  p: 1.5,
                  borderRadius: 2,
                  my: 1,
                },
                "& code": {
                  fontSize: "0.85rem",
                  fontFamily: fonts.mono,
                },
                "& pre code": {
                  whiteSpace: "pre",
                  overflowWrap: "normal",
                  wordBreak: "normal",
                  fontSize: 13,
                },
                "& :not(pre) > code": {
                  overflowWrap: "anywhere",
                  wordBreak: "break-word",
                  whiteSpace: "break-spaces",
                },
                "& a": {
                  color: brand.cyan,
                  textDecoration: "none",
                  "&:hover": { textDecoration: "underline" },
                },
                // GFM tables (enabled via remark-gfm): compact, scrollable
                // container so a wide table doesn't blow out the bubble.
                "& .md-table-wrap": {
                  minWidth: 0,
                  maxWidth: "100%",
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
            component="section"
            aria-label="Sources"
            className="source-cards"
            data-testid="citation-sources"
            sx={{
              display: "flex",
              flexWrap: "wrap",
              gap: 1,
              mt: "14px",
              width: "100%",
              minWidth: 0,
              maxWidth: "100%",
            }}
          >
            {footerSources.map((c) => (
              <Box
                key={c.number}
                component="button"
                type="button"
                className="source-card"
                data-testid="citation-source"
                aria-label={`Open source ${c.number}: ${citationLabel(c)}`}
                onClick={() => handleCitationClick(c)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    handleCitationClick(c);
                  }
                }}
                sx={{
                  display: "block",
                  flex: "0 1 320px",
                  width: 320,
                  minWidth: 0,
                  maxWidth: "100%",
                  cursor: "pointer",
                  textAlign: "left",
                  p: "10px 13px",
                  color: brand.text,
                  bgcolor: brand.surface,
                  border: `1px solid ${brand.line}`,
                  borderRadius: "5px",
                  fontFamily: fonts.body,
                  touchAction: "manipulation",
                  "&:hover": { borderColor: brand.cyan },
                  "&:focus-visible": {
                    outline: `2px solid ${brand.cyan}`,
                    outlineOffset: 3,
                  },
                }}
              >
                <Box
                  component="span"
                  sx={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 1,
                    minWidth: 0,
                  }}
                >
                  <Box
                    component="span"
                    sx={{
                      flexShrink: 0,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      minWidth: 18,
                      height: 18,
                      borderRadius: "3px",
                      color: brand.cyan,
                      bgcolor: `${brand.cyan}10`,
                      fontSize: 11,
                      fontFamily: fonts.mono,
                    }}
                  >
                    {c.number}
                  </Box>
                  <Typography
                    component="span"
                    className="source-card-title"
                    sx={{
                      minWidth: 0,
                      flex: 1,
                      display: "-webkit-box",
                      WebkitBoxOrient: "vertical",
                      WebkitLineClamp: 2,
                      overflow: "hidden",
                      overflowWrap: "anywhere",
                      fontSize: 13,
                      lineHeight: 1.45,
                      fontWeight: 500,
                    }}
                  >
                    {citationLabel(c)}
                  </Typography>
                  <Typography
                    component="span"
                    sx={{
                      flexShrink: 0,
                      color: brand.muted,
                      fontSize: 11,
                      lineHeight: 1.45,
                    }}
                  >
                    {c.source_type === "code" ? "Code" : "Document"}
                  </Typography>
                </Box>
                {c.excerpt && (
                  <Typography
                    component="span"
                    className="source-card-excerpt"
                    sx={{
                      display: "-webkit-box",
                      WebkitBoxOrient: "vertical",
                      WebkitLineClamp: 2,
                      overflow: "hidden",
                      overflowWrap: "anywhere",
                      whiteSpace: "normal",
                      color: brand.muted,
                      fontSize: 12,
                      lineHeight: 1.55,
                      mt: "6px",
                    }}
                  >
                    {citationPreview(c.excerpt)}
                  </Typography>
                )}
              </Box>
            ))}
          </Box>
        )}
        {!isUser && (
          <Box sx={{ display: "flex", gap: 2, alignItems: "center", mt: 1 }}>
            <Button
              size="small"
              startIcon={<ContentCopyIcon sx={{ fontSize: 14 }} />}
              sx={{
                color: brand.muted,
                minHeight: 32,
                p: 0,
                fontWeight: 400,
                fontSize: 13,
              }}
              onClick={() => {
                void navigator.clipboard
                  .writeText(content)
                  .then(() => toast.showSuccess("Answer copied."))
                  .catch((err) =>
                    toast.showError(err, "Couldn’t copy answer.")
                  );
              }}
            >
              Copy answer
            </Button>
            {debug && (
              <Button
                size="small"
                sx={{
                  color: brand.cyan,
                  minHeight: 32,
                  p: 0,
                  fontWeight: 400,
                  fontSize: 13,
                }}
                onClick={() => setInspectOpen(true)}
              >
                Inspect response
              </Button>
            )}
          </Box>
        )}
      </Box>
      <Dialog
        open={!!excerptSource}
        onClose={() => setExcerptSource(null)}
        maxWidth="sm"
        fullWidth
        aria-labelledby="source-excerpt-title"
        slotProps={{
          paper: {
            sx: {
              m: 2,
              width: "calc(100% - 32px)",
              maxWidth: 520,
              maxHeight: "calc(100dvh - 48px)",
            },
          },
        }}
      >
        <DialogTitle
          id="source-excerpt-title"
          sx={{
            fontSize: 18,
            lineHeight: 1.45,
            overflowWrap: "anywhere",
            display: "-webkit-box",
            WebkitBoxOrient: "vertical",
            WebkitLineClamp: 2,
            overflow: "hidden",
          }}
        >
          {excerptSource ? citationLabel(excerptSource) : "Source"}
        </DialogTitle>
        <DialogContent>
          <Typography sx={{ fontSize: 12, color: brand.cyan, mb: 1 }}>
            Retrieved{" "}
            {excerptSource?.source_type === "code" ? "code" : "document"}{" "}
            excerpt
          </Typography>
          <Typography
            data-testid="source-excerpt-text"
            sx={{
              fontSize: 14,
              lineHeight: 1.65,
              overflowWrap: "anywhere",
              whiteSpace: "normal",
            }}
          >
            {excerptSource?.excerpt
              ? citationPreview(excerptSource.excerpt)
              : "No excerpt was returned for this source."}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setExcerptSource(null)}>Close</Button>
        </DialogActions>
      </Dialog>
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
