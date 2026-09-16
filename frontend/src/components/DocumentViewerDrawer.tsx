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
import { useEffect, useState } from "react";
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
    primary = <MarkdownRender content={content} />;
  } else if (viewable_as === "code") {
    primary = (
      <CodeRender
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
  // The extracted `content` is the document's chunks re-joined with blank
  // lines — fine for prose, mangled for JSON/code. When the original file is
  // stored, fetch it from the signed URL and show the real thing.
  const [original, setOriginal] = useState<string | null>(null);
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
      });
    return () => {
      cancelled = true;
    };
  }, [fileUrl]);

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

  if (hl && lang) {
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

function MarkdownRender({ content }: { content: string }) {
  const hl = useHighlighter();
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
  if (!state) {
    return <TextRender content={content} />;
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
        {content || "(empty)"}
      </Renderer>
    </Box>
  );
}
