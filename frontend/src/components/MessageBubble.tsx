import { useState } from "react";
import { Box, Paper, Typography, Chip, alpha } from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import TravelExploreIcon from "@mui/icons-material/TravelExplore";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { DebugTrace } from "../lib/api";
import InspectDialog from "./InspectDialog";

interface MessageBubbleProps {
  role: "user" | "assistant";
  content: string;
  debug?: DebugTrace;
}

export default function MessageBubble({
  role,
  content,
  debug,
}: MessageBubbleProps) {
  const isUser = role === "user";
  const [inspectOpen, setInspectOpen] = useState(false);

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
            width: 28,
            height: 28,
            borderRadius: 1.5,
            bgcolor: alpha("#FF2E93", 0.15),
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            mt: 0.5,
          }}
        >
          <AutoAwesomeIcon sx={{ fontSize: 14, color: "#a78bfa" }} />
        </Box>
      )}
      <Box
        sx={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          maxWidth: "70%",
          minWidth: 0,
        }}
      >
        <Paper
          elevation={0}
          sx={{
            px: 2,
            py: 1.5,
            width: "100%",
            bgcolor: isUser ? alpha("#FF2E93", 0.15) : alpha("#1e1e2e", 0.6),
            border: 1,
            borderColor: isUser
              ? alpha("#FF2E93", 0.25)
              : alpha("#ffffff", 0.06),
            backdropFilter: "blur(10px)",
            WebkitBackdropFilter: "blur(10px)",
            borderRadius: 3,
          }}
        >
          {isUser ? (
            <Typography sx={{ fontSize: "0.925rem" }}>{content}</Typography>
          ) : (
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
                  fontFamily: '"JetBrains Mono", "Fira Code", monospace',
                },
                "& a": {
                  color: "#93c5fd",
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
                  bgcolor: alpha("#FF2E93", 0.12),
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
                  borderLeft: `3px solid ${alpha("#FF2E93", 0.5)}`,
                  color: alpha("#ffffff", 0.75),
                },
                fontSize: "0.925rem",
              }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Wrap every table so we can scroll horizontally without
                  // stretching the whole message bubble.
                  table: (props) => (
                    <div className="md-table-wrap">
                      <table {...props} />
                    </div>
                  ),
                }}
              >
                {content}
              </ReactMarkdown>
            </Box>
          )}
        </Paper>
        {!isUser && debug && (
          <Chip
            icon={<TravelExploreIcon sx={{ fontSize: 15 }} />}
            label="Inspect"
            size="small"
            onClick={() => setInspectOpen(true)}
            sx={{
              mt: 0.75,
              cursor: "pointer",
              bgcolor: alpha("#22d3ee", 0.1),
              color: "#22d3ee",
              border: `1px solid ${alpha("#22d3ee", 0.3)}`,
              "& .MuiChip-icon": { color: "#22d3ee" },
              "&:hover": { bgcolor: alpha("#22d3ee", 0.2) },
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
