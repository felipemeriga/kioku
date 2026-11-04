import { useState } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  Box,
  Button,
  Tab,
  Tabs,
  Chip,
  Typography,
  IconButton,
  Link,
  alpha,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { fetchToolArtifact, type Citation, type DebugTrace } from "../lib/api";
import { brand, fonts, scanlines } from "../theme";
import CornerCard from "./neo/CornerCard";
import RerankBar from "./neo/RerankBar";
import InspectCode from "./InspectCode";

interface InspectDialogProps {
  open: boolean;
  onClose: () => void;
  trace: DebugTrace;
  citations?: Citation[];
  onOpenDocument?: (filename: string, folderId?: string | null) => void;
}

const MONO = fonts.mono;

export default function InspectDialog({
  open,
  onClose,
  trace,
  citations = [],
  onOpenDocument,
}: InspectDialogProps) {
  const [tab, setTab] = useState(0);
  const [artifacts, setArtifacts] = useState<Record<string, string>>({});
  const reasoning = trace.reasoning ?? [];
  const toolCalls = trace.tool_calls ?? [];
  const chunks = trace.retrieval ?? [];
  const hasBackendRetrieval = toolCalls.some((t) =>
    ["backend_retrieval", "backend_bootstrap"].includes(t.origin ?? ""),
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth={false}
      fullWidth
      PaperProps={{
        sx: {
          maxWidth: 750,
          width: "calc(100% - 32px)",
          bgcolor: brand.surface2,
          backgroundImage: scanlines,
          border: `1px solid ${brand.cyan}`,
          borderRadius: "8px",
          boxShadow: `0 0 4px ${brand.cyan}88, 0 0 24px ${brand.cyan}33, 0 24px 64px rgba(0,0,0,0.7)`,
          // Bound the modal and make it a flex column whose Paper never scrolls
          // (overflow:hidden) — so a tall tab scrolls the DialogContent body
          // only, keeping the header + tabs pinned instead of scrolling them off
          // the top (MUI's Paper has overflowY:auto by default, which carried
          // the tabs away on long reasoning/tool-call content).
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        },
      }}
    >
      <DialogTitle
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          pb: 1,
          px: "24px",
          pt: "20px",
          flexShrink: 0,
        }}
      >
        <Typography
          sx={{ fontWeight: 700, fontSize: "19px", color: brand.text }}
        >
          Inspect
        </Typography>
        {trace.model && (
          <Chip
            label={trace.model}
            size="small"
            sx={{
              bgcolor: `${brand.cyan}14`,
              color: brand.cyan,
              border: `1px solid ${brand.cyan}66`,
              fontFamily: MONO,
              fontSize: 12,
              fontWeight: 600,
              borderRadius: "3px",
              height: "auto",
              "& .MuiChip-label": { px: "8px", py: "3px" },
            }}
          />
        )}
        <Box sx={{ flex: 1 }} />
        <IconButton
          onClick={onClose}
          size="small"
          aria-label="Close"
          sx={{
            width: 34,
            height: 34,
            borderRadius: "3px",
            border: `1px solid ${brand.line}`,
            color: brand.muted,
            fontSize: 15,
          }}
        >
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{
          px: "22px",
          borderBottom: `1px solid ${brand.line}`,
          minHeight: 0,
          flexShrink: 0,
          "& .MuiTabs-indicator": { display: "none" },
          "& .MuiTab-root": {
            textTransform: "none",
            minHeight: 44,
            fontWeight: 600,
            fontSize: 14,
            color: brand.muted,
            px: "16px",
            "&.Mui-selected": {
              color: brand.magentaGlow,
              bgcolor: "transparent",
              boxShadow: `inset 0 -2px 0 ${brand.magenta}`,
            },
          },
        }}
      >
        <Tab
          label={
            trace.execution ? "Execution" : `Reasoning (${reasoning.length})`
          }
        />
        <Tab
          label={`${hasBackendRetrieval ? "Retrieval and tools" : "Tool calls"} (${toolCalls.length})`}
        />
        <Tab label={`Chunks (${chunks.length})`} />
      </Tabs>

      <DialogContent
        sx={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          px: "24px",
          py: "24px",
        }}
      >
        {tab === 0 && (
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {trace.execution && (
              <InspectCode language="json">
                {JSON.stringify(trace.execution, null, 2)}
              </InspectCode>
            )}
            {!trace.execution && reasoning.length === 0 && (
              <Typography sx={{ color: alpha(brand.text, 0.5), fontSize: 13 }}>
                No reasoning captured — this answer ran without extended
                thinking (Fast mode).
              </Typography>
            )}
            {reasoning.map((r, i) => (
              <Box key={i}>
                <Chip
                  label={`Round ${r.round}`}
                  size="small"
                  sx={{
                    mb: 0.75,
                    bgcolor: `${brand.magenta}12`,
                    color: brand.magentaGlow,
                    border: `1px solid ${brand.magenta}44`,
                    fontFamily: MONO,
                    borderRadius: "3px",
                  }}
                />
                <InspectCode>{r.text}</InspectCode>
              </Box>
            ))}
          </Box>
        )}

        {tab === 1 && (
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {toolCalls.length === 0 && (
              <Typography sx={{ color: alpha(brand.text, 0.5), fontSize: 13 }}>
                No tool calls — the model answered directly.
              </Typography>
            )}
            {toolCalls.map((t, i) => (
              <Box
                key={i}
                sx={{
                  p: 1.5,
                  borderRadius: 1,
                  border: `1px solid ${brand.line}`,
                  bgcolor: brand.surface,
                }}
              >
                <Box
                  sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}
                >
                  <Chip
                    label={t.name}
                    size="small"
                    sx={{
                      bgcolor: `${brand.cyan}15`,
                      color: brand.cyan,
                      fontWeight: 600,
                      fontFamily: MONO,
                      borderRadius: "3px",
                      border: `1px solid ${brand.cyan}44`,
                    }}
                  />
                  {t.origin === "backend_bootstrap" ||
                  t.origin === "backend_retrieval" ? (
                    <Typography sx={{ color: brand.muted, fontSize: 12 }}>
                      {t.origin === "backend_bootstrap"
                        ? "Backend initial retrieval"
                        : "Backend retrieval"}
                    </Typography>
                  ) : null}
                  <Typography sx={{ color: brand.muted, fontSize: 12 }}>
                    {t.round !== undefined
                      ? `round ${t.round}`
                      : (t.status ?? "completed")}
                  </Typography>
                  {t.is_error && (
                    <Chip label="error" size="small" color="error" />
                  )}
                </Box>
                {t.started_at && (
                  <Typography sx={{ fontSize: 12, color: brand.muted }}>
                    Timing: {t.started_at} → {t.finished_at ?? "in progress"}
                  </Typography>
                )}
                <Typography sx={{ color: brand.muted, fontSize: 13, mb: 0.5 }}>
                  input
                </Typography>
                <InspectCode>
                  {t.input != null
                    ? JSON.stringify(t.input, null, 2)
                    : t.query
                      ? JSON.stringify({ query: t.query }, null, 2)
                      : "No input recorded."}
                </InspectCode>
                <Typography
                  sx={{
                    color: brand.muted,
                    fontSize: 13,
                    mt: 1,
                    mb: 0.5,
                  }}
                >
                  result
                </Typography>
                <InspectCode>
                  {(t.artifact_id && artifacts[t.artifact_id]) ??
                    t.result_preview ??
                    "Result available in the evidence artifact."}
                </InspectCode>
                {t.artifact_id && trace.execution?.job_id && (
                  <>
                    <Button
                      size="small"
                      onClick={() => {
                        const id = t.artifact_id!;
                        setArtifacts((previous) => ({
                          ...previous,
                          [id]: "Loading…",
                        }));
                        void fetchToolArtifact(trace.execution!.job_id, id)
                          .then((artifact) => {
                            setArtifacts((previous) => ({
                              ...previous,
                              [id]: artifact.result,
                            }));
                          })
                          .catch((error: unknown) => {
                            setArtifacts((previous) => ({
                              ...previous,
                              [id]:
                                error instanceof Error
                                  ? error.message
                                  : "Could not load evidence",
                            }));
                          });
                      }}
                    >
                      View exact returned evidence
                    </Button>
                  </>
                )}
              </Box>
            ))}
          </Box>
        )}

        {tab === 2 && (
          <Box sx={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            {chunks.length === 0 && (
              <Typography sx={{ color: alpha(brand.text, 0.5), fontSize: 13 }}>
                No chunks retrieved for this answer.
              </Typography>
            )}
            {chunks.map((c, i) => {
              const score = c.rerank_score;
              const filename = c.source + (c.symbol ? ` · ${c.symbol}` : "");
              const file = c.source.replace(/:\d+(?:-\d+)?$/, "");
              const matching = citations.filter(
                (citation) =>
                  citation.source_type === c.source_type &&
                  (!c.folder_id || citation.folder_id === c.folder_id) &&
                  (citation.source === c.source || citation.file === file),
              );
              const exact = matching.filter(
                (candidate) => candidate.source === c.source,
              );
              const candidates = exact.length ? exact : matching;
              const identities = new Set(
                candidates.map((candidate) =>
                  JSON.stringify([
                    candidate.folder_id,
                    candidate.file,
                    candidate.url?.split("#")[0],
                  ]),
                ),
              );
              const citation =
                candidates.length && identities.size === 1
                  ? candidates[0]
                  : undefined;
              let githubUrl: string | undefined;
              if (c.source_type === "code" && citation?.url) {
                try {
                  const url = new URL(citation.url);
                  if (
                    url.protocol === "https:" &&
                    url.hostname === "github.com"
                  ) {
                    const range = c.source.match(/:(\d+)(?:-(\d+))?$/);
                    if (range)
                      url.hash = `L${range[1]}${range[2] ? `-L${range[2]}` : ""}`;
                    githubUrl = url.toString();
                  }
                } catch {
                  /* Historical sources may have no valid URL. */
                }
              }
              const sourceLabel = githubUrl ? (
                <Link
                  href={githubUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{ color: brand.cyan }}
                >
                  {filename}
                </Link>
              ) : c.source_type !== "code" && onOpenDocument ? (
                <Link
                  component="button"
                  onClick={() => {
                    onClose();
                    onOpenDocument(
                      c.source,
                      c.folder_id ?? citation?.folder_id,
                    );
                  }}
                  sx={{ color: brand.cyan, textAlign: "left", font: "inherit" }}
                >
                  {filename}
                </Link>
              ) : (
                filename
              );
              return (
                <CornerCard
                  key={i}
                  color={brand.cyan}
                  sx={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "10px",
                    p: "14px 16px",
                  }}
                >
                  {score != null ? (
                    <RerankBar
                      file={sourceLabel}
                      score={score}
                      kind={c.source_type}
                    />
                  ) : (
                    <Typography sx={{ color: brand.text }}>
                      {sourceLabel} · rerank score unavailable
                    </Typography>
                  )}
                  {c.date && (
                    <Typography sx={{ color: brand.muted, fontSize: 13 }}>
                      {c.date}
                    </Typography>
                  )}
                  <InspectCode
                    filename={c.source_type === "code" ? c.source : undefined}
                  >
                    {c.content}
                  </InspectCode>
                </CornerCard>
              );
            })}
          </Box>
        )}
      </DialogContent>
    </Dialog>
  );
}
