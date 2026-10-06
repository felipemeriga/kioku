import { useState } from "react";
import { Box, Typography, Chip, alpha } from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { DebugTrace } from "../lib/api";
import InspectDialog from "./InspectDialog";
import CornerCard from "./neo/CornerCard";
import { brand, fonts } from "../theme";

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
          maxWidth: "70%",
          minWidth: 0,
        }}
      >
        {isUser ? (
          /* ── User bubble ── right-aligned, magenta tint */
          <Box
            sx={{
              px: 2,
              py: 1.5,
              background: `${brand.magenta}15`,
              border: `1px solid ${brand.magenta}25`,
              borderRadius: "12px 12px 3px 12px",
            }}
          >
            <Typography
              sx={{
                fontSize: "0.925rem",
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
          /* ── Assistant bubble ── CornerCard with cyan corners */
          <CornerCard
            color={brand.cyan}
            corners={2}
            sx={{ px: 2.25, py: 2, width: "100%" }}
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
                fontSize: "0.925rem",
                // Break long unbreakable tokens (bare URLs, inline code) so
                // they wrap instead of overflowing the bubble. Code blocks
                // keep their own horizontal scroll via the `& pre` rule above.
                overflowWrap: "anywhere",
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
          </CornerCard>
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
