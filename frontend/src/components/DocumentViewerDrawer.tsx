/**
 * DocumentViewerDrawer — right-hand drawer that previews a stored document.
 *
 * Self-contained: give it a filename (+ optional folder scope) and it fetches
 * the extracted text, a viewable_as hint, and a short-lived signed URL for
 * the original binary, then renders the best view — inline PDF/image/audio/
 * video, markdown, code, or plain text — with a toggle to inspect the
 * extracted text the RAG search actually sees.
 *
 * Extracted from FolderDetailPage so the Documents page can open docs too.
 */
import { useEffect, useMemo, useState } from "react";
import { List, type RowComponentProps } from "react-window";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Drawer,
  IconButton,
  Link as MuiLink,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DescriptionIcon from "@mui/icons-material/Description";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";

import { fetchDocumentContent, type DocumentContent } from "../lib/api";
import { brand, fonts } from "../theme";
import { useToast } from "./ToastProvider";

export default function DocumentViewerDrawer({
  filename,
  folderId,
  onClose,
}: {
  /** Document to show; null keeps the drawer closed. */
  filename: string | null;
  /** Optional folder scope for the content lookup. */
  folderId?: string | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const [doc, setDoc] = useState<DocumentContent | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!filename) {
      setDoc(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    // Loading placeholder — real values arrive from fetchDocumentContent.
    setDoc({
      source_filename: filename,
      source_type: null,
      metadata: {},
      chunk_count: 0,
      folder_id: folderId ?? null,
      status: null,
      created_at: null,
      content: "",
      viewable_as: "text",
      file_url: null,
      bucket: null,
    });
    fetchDocumentContent(filename, folderId ?? undefined)
      .then((d) => {
        if (!cancelled) setDoc(d);
      })
      .catch((err) => {
        if (!cancelled) {
          toast.showError(err, "Couldn't load document content.");
          setDoc(null);
          onClose();
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filename, folderId]);

  const handleCopy = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
      toast.showSuccess("Copied to clipboard.");
    } catch (err) {
      toast.showError(err, "Couldn't copy.");
    }
  };

  return (
    <Drawer
      anchor="right"
      open={!!filename}
      onClose={onClose}
      PaperProps={{
        sx: {
          width: { xs: "100%", sm: 640 },
          bgcolor: brand.ink,
          borderLeft: `1px solid ${brand.line}`,
        },
      }}
    >
      <DrawerBody doc={doc} loading={loading} onClose={onClose} onCopy={handleCopy} />
    </Drawer>
  );
}

function DrawerBody({
  doc,
  loading,
  onClose,
  onCopy,
}: {
  doc: DocumentContent | null;
  loading: boolean;
  onClose: () => void;
  onCopy: (content: string) => void;
}) {
  const [showExtracted, setShowExtracted] = useState(false);
  if (!doc) return null;
  const meta = doc.metadata || {};
  const githubUrl = typeof meta.url === "string" ? (meta.url as string) : null;
  const notionUrl = doc.notion_page_id
    ? `https://www.notion.so/${doc.notion_page_id.replace(/-/g, "")}`
    : null;
  const canShowExtracted =
    !!doc.content &&
    doc.viewable_as !== "text" &&
    doc.viewable_as !== "markdown" &&
    doc.viewable_as !== "code";
  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Box
        sx={{
          px: 2,
          py: 1.5,
          borderBottom: `1px solid ${brand.line}`,
          display: "flex",
          alignItems: "center",
          gap: 1,
        }}
      >
        <DescriptionIcon fontSize="small" sx={{ color: brand.cyan }} />
        <Typography
          sx={{
            flex: 1,
            fontFamily: fonts.mono,
            fontSize: "0.85rem",
            color: brand.text,
          }}
          noWrap
        >
          {doc.source_filename}
        </Typography>
        <Tooltip title="Copy extracted text">
          <span>
            <IconButton
              size="small"
              onClick={() => onCopy(doc.content)}
              disabled={loading || !doc.content}
              sx={{ color: brand.muted, "&:hover": { color: brand.text } }}
            >
              <ContentCopyIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
        {notionUrl && (
          <Tooltip title="Open in Notion">
            <IconButton
              size="small"
              component={MuiLink}
              href={notionUrl}
              target="_blank"
              rel="noopener"
              sx={{ color: brand.muted, "&:hover": { color: brand.cyan } }}
            >
              <OpenInNewIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
        {githubUrl && (
          <Tooltip title="Open on GitHub">
            <IconButton
              size="small"
              component={MuiLink}
              href={githubUrl}
              target="_blank"
              rel="noopener"
              sx={{ color: brand.muted, "&:hover": { color: brand.cyan } }}
            >
              <OpenInNewIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
        {doc.file_url && (
          <Tooltip title="Open original file in new tab">
            <IconButton
              size="small"
              component={MuiLink}
              href={doc.file_url}
              target="_blank"
              rel="noopener"
              sx={{ color: brand.muted, "&:hover": { color: brand.cyan } }}
            >
              <OpenInNewIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
        <IconButton size="small" onClick={onClose} sx={{ color: brand.muted }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>
      <Box sx={{ px: 2, py: 1, borderBottom: `1px solid ${brand.line}` }}>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: "0.7rem",
            color: brand.muted,
          }}
        >
          {doc.viewable_as} · {doc.source_type} · {doc.chunk_count} chunks
          {doc.status ? ` · ${doc.status}` : ""}
          {doc.created_at ? ` · ${new Date(doc.created_at).toLocaleString()}` : ""}
        </Typography>
      </Box>
      <Box sx={{ flex: 1, overflow: "auto", position: "relative" }}>
        {loading ? (
          <Box sx={{ p: 3 }}>
            <CircularProgress size={20} sx={{ color: brand.violet2 }} />
          </Box>
        ) : (
          <DocumentRenderer
            doc={doc}
            showExtracted={showExtracted}
            onToggleExtracted={
              canShowExtracted ? () => setShowExtracted((v) => !v) : undefined
            }
          />
        )}
      </Box>
    </Box>
  );
}

function DocumentRenderer({
  doc,
  showExtracted,
  onToggleExtracted,
}: {
  doc: DocumentContent;
  showExtracted: boolean;
  onToggleExtracted?: () => void;
}) {
  const { viewable_as, file_url, content } = doc;

  // The renderer for the ORIGINAL file (image/pdf/audio/video/markdown/code/text).
  let primary: React.ReactNode = null;
  if (viewable_as === "image") {
    primary = file_url ? (
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          bgcolor: alpha("#000", 0.35),
          minHeight: "100%",
          p: 2,
        }}
      >
        <Box
          component="img"
          src={file_url}
          alt={doc.source_filename}
          sx={{
            maxWidth: "100%",
            maxHeight: "80vh",
            borderRadius: 1,
            boxShadow: `0 8px 24px -12px ${alpha("#000", 0.6)}`,
          }}
        />
      </Box>
    ) : (
      <NoOriginalFallback msg="Original image not available; showing extracted OCR text below." />
    );
  } else if (viewable_as === "pdf") {
    primary = file_url ? (
      <Box
        component="iframe"
        src={file_url}
        title={doc.source_filename}
        sx={{ width: "100%", height: "100%", border: 0, bgcolor: "#fff" }}
      />
    ) : (
      <NoOriginalFallback msg="Original PDF not available; showing extracted text below." />
    );
  } else if (viewable_as === "audio") {
    primary = file_url ? (
      <Box sx={{ p: 3 }}>
        <Box component="audio" controls src={file_url} sx={{ width: "100%" }} />
      </Box>
    ) : (
      <NoOriginalFallback msg="Original audio not available; showing transcript below." />
    );
  } else if (viewable_as === "video") {
    primary = file_url ? (
      <Box sx={{ p: 2 }}>
        <Box
          component="video"
          controls
          src={file_url}
          sx={{ width: "100%", maxHeight: "80vh" }}
        />
      </Box>
    ) : (
      <NoOriginalFallback msg="Original video not available." />
    );
  } else if (viewable_as === "markdown") {
    primary = (
      <MarkdownRender
        key={doc.source_filename}
        content={content}
        fileUrl={file_url}
      />
    );
  } else if (viewable_as === "code") {
    primary = (
      <CodeRender
        key={doc.source_filename}
        content={content}
        filename={doc.source_filename}
        fileUrl={file_url}
      />
    );
  } else {
    primary = <TextRender content={content} />;
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Box
        sx={{
          flex: showExtracted ? 1 : "1 1 100%",
          overflow: "auto",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {primary}
      </Box>
      {onToggleExtracted && (
        <Box
          sx={{
            borderTop: `1px solid ${brand.line}`,
            bgcolor: alpha(brand.surface, 0.7),
          }}
        >
          <Button
            fullWidth
            onClick={onToggleExtracted}
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.7rem",
              letterSpacing: "0.14em",
              color: brand.muted,
              textTransform: "uppercase",
              borderRadius: 0,
              py: 0.75,
            }}
          >
            {showExtracted ? "Hide" : "Show"} extracted text (searched by RAG)
          </Button>
          {showExtracted && (
            <Box
              sx={{
                borderTop: `1px solid ${brand.line}`,
                maxHeight: 240,
                overflow: "auto",
                px: 2,
                py: 1.5,
              }}
            >
              <TextRender content={content} />
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}

function NoOriginalFallback({ msg }: { msg: string }) {
  return (
    <Alert severity="info" sx={{ m: 2 }}>
      {msg}
    </Alert>
  );
}

function TextRender({ content }: { content: string }) {
  if (content.length > HIGHLIGHT_CHAR_LIMIT) {
    return (
      <Box sx={{ height: "100%", minHeight: 240 }}>
        <VirtualCode text={content} />
      </Box>
    );
  }
  return (
    <Typography
      component="pre"
      sx={{
        fontFamily: fonts.mono,
        fontSize: "0.82rem",
        color: brand.text,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        m: 0,
        px: 2,
        py: 2,
      }}
    >
      {content || "(empty)"}
    </Typography>
  );
}

const EXT_TO_LANG: Record<string, string> = {
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  toml: "toml",
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  rs: "rust",
  go: "go",
  java: "java",
  c: "c",
  cpp: "cpp",
  sh: "bash",
  sql: "sql",
  html: "markup",
  css: "css",
};

/** Lazy-load the Prism highlighter (like ReactMarkdown above) so it only
 *  ships for users who actually open a code document. */
function useHighlighter() {
  const [hl, setHl] = useState<{
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    SyntaxHighlighter: React.ComponentType<any>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    style: any;
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      import("react-syntax-highlighter"),
      import("react-syntax-highlighter/dist/esm/styles/prism/one-dark"),
    ]).then(([m, s]) => {
      if (!cancelled)
        setHl({ SyntaxHighlighter: m.PrismAsync, style: s.default });
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return hl;
}

// Prism emits a DOM node per token — past this size the element count
// freezes the tab. Bigger files render as a plain (fast) <pre> instead.
const HIGHLIGHT_CHAR_LIMIT = 120_000;

/** Download the stored original file from its signed URL. The extracted
 *  `content` is the document's chunks re-joined with blank lines — fine for
 *  prose search, but it mangles JSON/code and can break markdown fencing
 *  (and legacy uploads may join out of order). Callers key their component
 *  by filename so a new document remounts with fresh state. */
function useOriginalText(fileUrl?: string | null) {
  const [original, setOriginal] = useState<string | null>(null);
  const [fetching, setFetching] = useState(!!fileUrl);
  useEffect(() => {
    if (!fileUrl) return;
    let cancelled = false;
    fetch(fileUrl)
      .then((r) => (r.ok ? r.text() : null))
      .then((t) => {
        if (!cancelled && t !== null) setOriginal(t);
      })
      .catch(() => {
        // Fall back to extracted content silently.
      })
      .finally(() => {
        if (!cancelled) setFetching(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileUrl]);
  return { original, fetching };
}

function LoadingFile() {
  return (
    <Box sx={{ p: 3, display: "flex", alignItems: "center", gap: 1.5 }}>
      <CircularProgress size={20} sx={{ color: brand.violet2 }} />
      <Typography variant="body2" sx={{ color: brand.muted }}>
        Loading and rendering your file…
      </Typography>
    </Box>
  );
}

function CodeRender({
  content,
  filename,
  fileUrl,
}: {
  content: string;
  filename?: string;
  fileUrl?: string | null;
}) {
  const hl = useHighlighter();
  const { original, fetching } = useOriginalText(fileUrl);

  if (fetching && original === null) {
    return <LoadingFile />;
  }

  let text = original ?? content;
  const ext = filename?.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "json") {
    try {
      text = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      // Not valid JSON as-is (e.g. chunk-joined extract) — show unformatted.
    }
  }
  const lang = EXT_TO_LANG[ext];
  const tooBigToHighlight = text.length > HIGHLIGHT_CHAR_LIMIT;

  if (hl && lang && !tooBigToHighlight) {
    return (
      <hl.SyntaxHighlighter
        language={lang}
        style={hl.style}
        customStyle={{
          margin: 0,
          padding: "16px",
          background: "transparent",
          fontSize: "0.82rem",
        }}
        codeTagProps={{ style: { fontFamily: fonts.mono } }}
        wrapLongLines
      >
        {text || "(empty)"}
      </hl.SyntaxHighlighter>
    );
  }

  if (tooBigToHighlight) {
    return (
      <Box
        sx={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}
      >
        <Typography
          variant="caption"
          sx={{ display: "block", px: 2, py: 1, color: brand.muted, flexShrink: 0 }}
        >
          Large file — rendering only the visible lines (highlighting off).
        </Typography>
        <Box sx={{ flex: 1, minHeight: 0, bgcolor: alpha("#000", 0.15) }}>
          <VirtualCode text={text} />
        </Box>
      </Box>
    );
  }

  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        px: 2,
        py: 2,
        fontFamily: fonts.mono,
        fontSize: "0.82rem",
        color: brand.text,
        bgcolor: alpha("#000", 0.15),
        whiteSpace: "pre",
        overflow: "auto",
      }}
    >
      <code>{text || "(empty)"}</code>
    </Box>
  );
}

const VIRTUAL_ROW_HEIGHT = 19;

function VirtualRow({
  index,
  style,
  lines,
}: RowComponentProps<{ lines: string[] }>) {
  return (
    <div
      style={{
        ...style,
        fontFamily: fonts.mono,
        fontSize: "0.8rem",
        lineHeight: `${VIRTUAL_ROW_HEIGHT}px`,
        whiteSpace: "pre",
        overflow: "hidden",
        paddingLeft: 16,
        paddingRight: 16,
        color: brand.text,
      }}
    >
      {lines[index]}
    </div>
  );
}

/** Windowed renderer for huge code/text files: only the visible lines exist
 *  in the DOM, so a multi-MB document scrolls like a small one. */
function VirtualCode({ text }: { text: string }) {
  const lines = useMemo(() => text.split("\n"), [text]);
  return (
    <List
      rowComponent={VirtualRow}
      rowCount={lines.length}
      rowHeight={VIRTUAL_ROW_HEIGHT}
      rowProps={{ lines }}
      overscanCount={20}
      style={{ height: "100%" }}
    />
  );
}

function MarkdownRender({
  content,
  fileUrl,
}: {
  content: string;
  fileUrl?: string | null;
}) {
  const hl = useHighlighter();
  // Prefer the stored original .md: the chunk-joined extract can re-join out
  // of order (legacy uploads) or split a code fence, which flips the whole
  // rest of the document into a code block.
  const { original, fetching } = useOriginalText(fileUrl);
  // Lazy-import ReactMarkdown + remark-gfm so they don't ship in the initial
  // bundle for folks who never open a markdown document. GFM adds tables,
  // task lists, strikethrough — the syntax GitHub commit/PR/issue bodies use.
  const [state, setState] = useState<{
    Renderer: React.ComponentType<{
      children: string;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      remarkPlugins?: any[];
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      components?: any;
    }>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    gfm: any;
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([import("react-markdown"), import("remark-gfm")]).then(
      ([md, gfm]) => {
        if (!cancelled) setState({ Renderer: md.default, gfm: gfm.default });
      }
    );
    return () => {
      cancelled = true;
    };
  }, []);
  if (fetching && original === null) {
    return <LoadingFile />;
  }
  const text = original ?? content;
  if (!state) {
    return <TextRender content={text} />;
  }
  // ReactMarkdown builds the full element tree at once — for a huge document
  // that would stall the tab, so fall back to the windowed plain view.
  if (text.length > HIGHLIGHT_CHAR_LIMIT * 3) {
    return (
      <Box sx={{ height: "100%", minHeight: 240 }}>
        <VirtualCode text={text} />
      </Box>
    );
  }
  const { Renderer, gfm } = state;
  return (
    <Box
      sx={{
        px: 3,
        py: 2,
        color: brand.text,
        fontFamily: fonts.body,
        fontSize: "0.92rem",
        lineHeight: 1.6,
        "& h1": {
          fontFamily: fonts.display,
          fontSize: "1.35rem",
          mb: 1,
          mt: 2,
        },
        "& h2": {
          fontFamily: fonts.display,
          fontSize: "1.15rem",
          mb: 0.75,
          mt: 2,
        },
        "& h3": {
          fontFamily: fonts.display,
          fontSize: "1.02rem",
          mb: 0.5,
          mt: 1.5,
        },
        "& p": { my: 1 },
        "& ul, & ol": { pl: 3, my: 1 },
        "& li": { mb: 0.25 },
        "& code": {
          fontFamily: fonts.mono,
          fontSize: "0.82rem",
          bgcolor: alpha("#000", 0.25),
          px: 0.75,
          py: 0.25,
          borderRadius: 0.75,
        },
        "& pre": {
          bgcolor: alpha("#000", 0.25),
          p: 1.5,
          borderRadius: 1,
          overflow: "auto",
          "& code": { bgcolor: "transparent", p: 0 },
        },
        "& a": {
          color: brand.cyan,
          textDecoration: "none",
          "&:hover": { textDecoration: "underline" },
        },
        "& blockquote": {
          borderLeft: `3px solid ${brand.violet2}`,
          pl: 2,
          color: brand.muted,
          my: 1,
        },
        "& hr": { borderColor: brand.line },
        "& table": { borderCollapse: "collapse", my: 1 },
        "& th, & td": { border: `1px solid ${brand.line}`, px: 1, py: 0.5 },
      }}
    >
      <Renderer
        remarkPlugins={[gfm]}
        components={{
          // Fenced blocks with a language tag get real syntax highlighting;
          // inline code and untagged blocks keep the default styling.
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          code: (props: any) => {
            const { className, children } = props;
            const match = /language-(\w+)/.exec(className || "");
            const body = String(children ?? "");
            if (hl && match && body.includes("\n")) {
              return (
                <hl.SyntaxHighlighter
                  language={match[1]}
                  style={hl.style}
                  customStyle={{
                    margin: 0,
                    padding: "12px",
                    background: "transparent",
                    fontSize: "0.82rem",
                  }}
                  codeTagProps={{ style: { fontFamily: fonts.mono } }}
                >
                  {body.replace(/\n$/, "")}
                </hl.SyntaxHighlighter>
              );
            }
            return <code className={className}>{children}</code>;
          },
        }}
      >
        {text || "(empty)"}
      </Renderer>
    </Box>
  );
}
