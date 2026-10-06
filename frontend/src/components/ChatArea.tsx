import { useEffect, useRef } from "react";
import { Box, Chip, Stack, Typography } from "@mui/material";
import MessageBubble from "./MessageBubble";
import ChatInput from "./ChatInput";
import ThinkingBar from "./ThinkingBar";
import type {
  Message,
  ChatFilters,
  ChatMode,
  ChatModel,
  ChatScope,
  StageEvent,
} from "../lib/api";
import { brand, fonts } from "../theme";

interface ChatAreaProps {
  messages: Message[];
  streamingContent: string;
  isStreaming: boolean;
  currentStage: StageEvent | null;
  onSend: (
    message: string,
    filters?: ChatFilters,
    model?: ChatModel,
    mode?: ChatMode,
    debug?: boolean
  ) => void;
  scope?: ChatScope | null;
  onPickScope?: () => void;
  onClearScope?: () => void;
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
  scope,
  onPickScope,
  onClearScope,
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
            <Stack
              alignItems="center"
              spacing={2.5}
              sx={{ height: "70vh", justifyContent: "center", px: 3 }}
            >
              {/* Brand glyph */}
              <Box
                sx={{
                  width: 54,
                  height: 54,
                  borderRadius: "6px",
                  border: `1.5px solid ${brand.magenta}`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: fonts.jp,
                  fontWeight: 900,
                  fontSize: "1.8rem",
                  color: brand.magentaGlow,
                  boxShadow: `0 0 4px ${brand.magenta}88, 0 0 16px ${brand.magenta}44`,
                }}
              >
                記
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
                  Query your repos, docs, and memories. Filter by topic or
                  metadata, or reach for the web when your corpus doesn't have
                  the answer.
                </Typography>
              </Stack>

              {/* Suggestion neon cards */}
              <Stack
                direction="row"
                spacing={1}
                flexWrap="wrap"
                justifyContent="center"
                sx={{ mt: 1, maxWidth: 600 }}
              >
                {SUGGESTIONS.map((text) => (
                  <Chip
                    key={text}
                    label={text}
                    variant="outlined"
                    onClick={() => onSend(text)}
                    sx={{
                      m: 0.5,
                      fontFamily: fonts.mono,
                      fontSize: "0.75rem",
                      borderRadius: "3px",
                      borderColor: `${brand.magenta}55`,
                      color: brand.muted,
                      bgcolor: `${brand.magenta}08`,
                      "&:hover": {
                        bgcolor: `${brand.magenta}18`,
                        borderColor: brand.magenta,
                        color: brand.text,
                        boxShadow: `0 0 10px ${brand.magenta}33`,
                      },
                    }}
                  />
                ))}
              </Stack>
            </Stack>
          )}
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              role={msg.role}
              content={msg.content}
              debug={msg.debug}
            />
          ))}
          {isStreaming && currentStage && !streamingContent && (
            <ThinkingBar stage={currentStage} />
          )}
          {isStreaming && streamingContent && (
            <MessageBubble role="assistant" content={streamingContent} />
          )}
          {/* Mid-answer: the model streamed a preamble, then went quiet for more
              tool rounds. Keep a "still working" indicator so it's not frozen. */}
          {isStreaming && currentStage && streamingContent && (
            <ThinkingBar stage={currentStage} />
          )}
          <div ref={bottomRef} />
        </Box>
      </Box>
      <ChatInput
        onSend={onSend}
        disabled={isStreaming}
        scope={scope}
        onPickScope={onPickScope}
        onClearScope={onClearScope}
      />
    </Box>
  );
}
