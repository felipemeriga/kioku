import { useEffect, useRef } from "react";
import { Box, Chip, Stack, Typography, alpha } from "@mui/material";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import MessageBubble from "./MessageBubble";
import ChatInput from "./ChatInput";
import ThinkingBar from "./ThinkingBar";
import type { Message, ChatFilters, StageEvent } from "../lib/api";
import { brand, fonts } from "../theme";

interface ChatAreaProps {
  messages: Message[];
  streamingContent: string;
  isStreaming: boolean;
  currentStage: StageEvent | null;
  onSend: (message: string, filters?: ChatFilters, fastMode?: boolean) => void;
}

const SUGGESTIONS = [
  "Summarize my documents",
  "What topics are covered?",
  "Search the web for latest news",
  "Show document stats",
];

export default function ChatArea({
  messages,
  streamingContent,
  isStreaming,
  currentStage,
  onSend,
}: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  return (
    <Box
      sx={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        height: "100vh",
      }}
    >
      <Box sx={{ flex: 1, overflow: "auto" }}>
        <Box sx={{ py: 3, px: 3 }}>
          {messages.length === 0 && !isStreaming && (
            <Stack alignItems="center" spacing={2.5} sx={{ height: "70vh", justifyContent: "center", px: 3 }}>
              <Box
                sx={{
                  width: 84,
                  height: 84,
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  background: `radial-gradient(circle at 30% 30%, ${brand.violet2} 0%, ${brand.violet} 45%, ${brand.violetDeep} 100%)`,
                  boxShadow: `0 10px 40px ${alpha(brand.violet, 0.5)}, inset 0 0 30px ${alpha("#000", 0.3)}`,
                }}
              >
                <AutoAwesomeIcon sx={{ fontSize: 40, color: "#fff" }} />
              </Box>

              <Stack spacing={0.5} alignItems="center">
                <Typography
                  variant="overline"
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: "0.62rem",
                    letterSpacing: "0.32em",
                    color: brand.cyan,
                  }}
                >
                  ● READY TO ANSWER
                </Typography>
                <Typography
                  sx={{
                    fontFamily: fonts.display,
                    fontWeight: 700,
                    fontSize: "1.6rem",
                    letterSpacing: "-0.02em",
                    color: brand.text,
                  }}
                >
                  Ask your second brain.
                </Typography>
                <Typography
                  sx={{
                    fontFamily: fonts.body,
                    fontSize: "0.9rem",
                    color: brand.muted,
                    textAlign: "center",
                    maxWidth: 460,
                    mt: 0.5,
                  }}
                >
                  Query your repos, docs, and memories. Filter by topic or metadata, or reach for the web when your corpus doesn't have the answer.
                </Typography>
              </Stack>

              <Stack direction="row" spacing={1} flexWrap="wrap" justifyContent="center" sx={{ mt: 1, maxWidth: 560 }}>
                {SUGGESTIONS.map((text) => (
                  <Chip
                    key={text}
                    label={text}
                    variant="outlined"
                    onClick={() => onSend(text)}
                    sx={{
                      m: 0.5,
                      borderColor: brand.line,
                      color: brand.muted,
                      fontFamily: fonts.body,
                      "&:hover": {
                        bgcolor: alpha(brand.violet, 0.1),
                        borderColor: brand.violet2,
                        color: brand.text,
                      },
                    }}
                  />
                ))}
              </Stack>
            </Stack>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} role={msg.role} content={msg.content} />
          ))}
          {isStreaming && currentStage && !streamingContent && (
            <ThinkingBar stage={currentStage} />
          )}
          {isStreaming && streamingContent && (
            <MessageBubble role="assistant" content={streamingContent} />
          )}
          <div ref={bottomRef} />
        </Box>
      </Box>
      <ChatInput onSend={onSend} disabled={isStreaming} />
    </Box>
  );
}
