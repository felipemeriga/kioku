import { useState } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  Box,
  Tabs,
  Tab,
  Chip,
  Typography,
  LinearProgress,
  IconButton,
  alpha,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { DebugTrace } from "../lib/api";

interface InspectDialogProps {
  open: boolean;
  onClose: () => void;
  trace: DebugTrace;
}

const MONO = '"JetBrains Mono", "Fira Code", monospace';

function Pre({ children }: { children: string }) {
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 1.25,
        fontFamily: MONO,
        fontSize: 12,
        lineHeight: 1.5,
        color: alpha("#fff", 0.85),
        bgcolor: alpha("#000", 0.35),
        borderRadius: 1.5,
        border: `1px solid ${alpha("#fff", 0.08)}`,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        overflowX: "auto",
      }}
    >
      {children}
    </Box>
  );
}

export default function InspectDialog({
  open,
  onClose,
  trace,
}: InspectDialogProps) {
  const [tab, setTab] = useState(0);
  const reasoning = trace.reasoning ?? [];
  const toolCalls = trace.tool_calls ?? [];
  const chunks = trace.retrieval ?? [];

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      fullWidth
      PaperProps={{
        sx: {
          bgcolor: "#121219",
          backgroundImage: "none",
          border: `1px solid ${alpha("#22d3ee", 0.25)}`,
          borderRadius: 3,
        },
      }}
    >
      <DialogTitle
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          pb: 1,
        }}
      >
        <Typography sx={{ fontWeight: 700, fontSize: "1.05rem" }}>
          Inspect
        </Typography>
        {trace.model && (
          <Chip
            label={trace.model}
            size="small"
            sx={{
              bgcolor: alpha("#a78bfa", 0.15),
              color: "#a78bfa",
              fontWeight: 600,
            }}
          />
        )}
        <Box sx={{ flex: 1 }} />
        <IconButton onClick={onClose} size="small">
          <CloseIcon fontSize="small" />
        </IconButton>
      </DialogTitle>
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{
          px: 3,
          borderBottom: `1px solid ${alpha("#fff", 0.08)}`,
          "& .MuiTab-root": { textTransform: "none", minHeight: 44 },
        }}
      >
        <Tab label={`Reasoning (${reasoning.length})`} />
        <Tab label={`Tool calls (${toolCalls.length})`} />
        <Tab label={`Chunks (${chunks.length})`} />
      </Tabs>
      <DialogContent sx={{ minHeight: 380 }}>
        {tab === 0 && (
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {reasoning.length === 0 && (
              <Typography sx={{ color: alpha("#fff", 0.5), fontSize: 13 }}>
                No reasoning captured — this answer ran without extended
                thinking (Fast mode).
              </Typography>
            )}
            {reasoning.map((r, i) => (
              <Box key={i}>
                <Chip
                  label={`Round ${r.round}`}
                  size="small"
                  sx={{ mb: 0.75, bgcolor: alpha("#a78bfa", 0.12) }}
                />
                <Pre>{r.text}</Pre>
              </Box>
            ))}
          </Box>
        )}

        {tab === 1 && (
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {toolCalls.length === 0 && (
              <Typography sx={{ color: alpha("#fff", 0.5), fontSize: 13 }}>
                No tool calls — the model answered directly.
              </Typography>
            )}
            {toolCalls.map((t, i) => (
              <Box
                key={i}
                sx={{
                  p: 1.5,
                  borderRadius: 2,
                  border: `1px solid ${alpha("#fff", 0.08)}`,
                }}
              >
                <Box
                  sx={{ display: "flex", alignItems: "center", gap: 1, mb: 1 }}
                >
                  <Chip
                    label={t.name}
                    size="small"
                    sx={{
                      bgcolor: alpha("#22d3ee", 0.15),
                      color: "#22d3ee",
                      fontWeight: 600,
                      fontFamily: MONO,
                    }}
                  />
                  <Typography sx={{ color: alpha("#fff", 0.4), fontSize: 12 }}>
                    round {t.round}
                  </Typography>
                  {t.is_error && (
                    <Chip label="error" size="small" color="error" />
                  )}
                </Box>
                <Typography
                  sx={{ color: alpha("#fff", 0.5), fontSize: 11, mb: 0.5 }}
                >
                  input
                </Typography>
                <Pre>{JSON.stringify(t.input, null, 2)}</Pre>
                <Typography
                  sx={{
                    color: alpha("#fff", 0.5),
                    fontSize: 11,
                    mt: 1,
                    mb: 0.5,
                  }}
                >
                  result
                </Typography>
                <Pre>{t.result_preview}</Pre>
              </Box>
            ))}
          </Box>
        )}

        {tab === 2 && (
          <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
            {chunks.length === 0 && (
              <Typography sx={{ color: alpha("#fff", 0.5), fontSize: 13 }}>
                No chunks retrieved for this answer.
              </Typography>
            )}
            {chunks.map((c, i) => {
              const isCode = c.source_type === "code";
              const score = c.rerank_score;
              return (
                <Box
                  key={i}
                  sx={{
                    p: 1.5,
                    borderRadius: 2,
                    border: `1px solid ${alpha("#fff", 0.08)}`,
                  }}
                >
                  <Box
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 1,
                      mb: 0.75,
                      flexWrap: "wrap",
                    }}
                  >
                    <Chip
                      label={isCode ? "code" : "doc"}
                      size="small"
                      sx={{
                        height: 20,
                        bgcolor: alpha(isCode ? "#34d399" : "#93c5fd", 0.15),
                        color: isCode ? "#34d399" : "#93c5fd",
                        fontWeight: 600,
                      }}
                    />
                    <Typography
                      sx={{ fontFamily: MONO, fontSize: 12, color: "#fff" }}
                    >
                      {c.source}
                      {c.symbol ? ` · ${c.symbol}` : ""}
                    </Typography>
                    {c.date && (
                      <Typography
                        sx={{ color: alpha("#fff", 0.4), fontSize: 11 }}
                      >
                        {c.date}
                      </Typography>
                    )}
                    <Box sx={{ flex: 1 }} />
                    <Typography
                      sx={{ color: alpha("#fff", 0.55), fontSize: 11 }}
                    >
                      rerank {score != null ? score.toFixed(3) : "—"}
                    </Typography>
                  </Box>
                  <LinearProgress
                    variant="determinate"
                    value={Math.max(0, Math.min(100, (score ?? 0) * 100))}
                    sx={{
                      height: 5,
                      borderRadius: 3,
                      mb: 1,
                      bgcolor: alpha("#fff", 0.08),
                      "& .MuiLinearProgress-bar": {
                        bgcolor: (score ?? 0) >= 0.45 ? "#34d399" : "#f59e0b",
                      },
                    }}
                  />
                  <Pre>{c.content}</Pre>
                </Box>
              );
            })}
          </Box>
        )}
      </DialogContent>
    </Dialog>
  );
}
