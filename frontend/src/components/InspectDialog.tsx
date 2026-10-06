import { useState } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  Box,
  Tab,
  Tabs,
  Chip,
  Typography,
  IconButton,
  alpha,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { DebugTrace } from "../lib/api";
import { brand, fonts, scanlines } from "../theme";
import CornerCard from "./neo/CornerCard";
import RerankBar from "./neo/RerankBar";

interface InspectDialogProps {
  open: boolean;
  onClose: () => void;
  trace: DebugTrace;
}

const MONO = fonts.mono;

function Pre({ children }: { children: string }) {
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: "12px 14px",
        fontFamily: MONO,
        fontSize: 13,
        lineHeight: 1.6,
        color: brand.text,
        bgcolor: brand.inkDeep,
        borderRadius: 1,
        border: `1px solid ${brand.line}`,
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
          bgcolor: brand.surface2,
          backgroundImage: scanlines,
          border: `1px solid ${brand.cyan}`,
          borderRadius: 1,
          boxShadow: `0 0 4px ${brand.cyan}88, 0 0 24px ${brand.cyan}33, 0 24px 64px rgba(0,0,0,0.7)`,
        },
      }}
    >
      <DialogTitle
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.5,
          pb: 1,
          px: "22px",
          pt: "18px",
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
              bgcolor: `${brand.magenta}18`,
              boxShadow: `inset 0 -2px 0 ${brand.magenta}`,
            },
          },
        }}
      >
        <Tab label={`Reasoning (${reasoning.length})`} />
        <Tab label={`Tool calls (${toolCalls.length})`} />
        <Tab label={`Chunks (${chunks.length})`} />
      </Tabs>

      <DialogContent sx={{ minHeight: 380, px: "22px", py: "20px" }}>
        {tab === 0 && (
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {reasoning.length === 0 && (
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
                <Pre>{r.text}</Pre>
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
                  <Typography sx={{ color: brand.muted, fontSize: 12 }}>
                    round {t.round}
                  </Typography>
                  {t.is_error && (
                    <Chip label="error" size="small" color="error" />
                  )}
                </Box>
                <Typography sx={{ color: brand.muted, fontSize: 11, mb: 0.5 }}>
                  input
                </Typography>
                <Pre>{JSON.stringify(t.input, null, 2)}</Pre>
                <Typography
                  sx={{
                    color: brand.muted,
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
          <Box sx={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            {chunks.length === 0 && (
              <Typography sx={{ color: alpha(brand.text, 0.5), fontSize: 13 }}>
                No chunks retrieved for this answer.
              </Typography>
            )}
            {chunks.map((c, i) => {
              const score = c.rerank_score ?? 0;
              const filename = c.source + (c.symbol ? ` · ${c.symbol}` : "");
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
                  <RerankBar
                    file={filename}
                    score={score}
                    kind={c.source_type}
                  />
                  {c.date && (
                    <Typography sx={{ color: brand.muted, fontSize: 11 }}>
                      {c.date}
                    </Typography>
                  )}
                  <Pre>{c.content}</Pre>
                </CornerCard>
              );
            })}
          </Box>
        )}
      </DialogContent>
    </Dialog>
  );
}
