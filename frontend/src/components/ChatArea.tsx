import { useEffect, useRef } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
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
  messagesLoading?: boolean;
  messagesError?: string | null;
  onRetryMessages?: () => void;
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
  /** Open a cited document in the in-app viewer drawer. */
  onOpenDocument?: (filename: string, folderId?: string | null) => void;
}

const SUGGESTIONS = [
  "Summarize my documents",
  "What topics are covered?",
  "Search the web for latest news",
  "Show document stats",
];

export default function ChatArea({
  messagesLoading = false,
  messagesError = null,
  onRetryMessages,
  messages,
  streamingContent,
  isStreaming,
  currentStage,
  onSend,
  scope,
  onPickScope,
  onClearScope,
  onOpenDocument,
}: ChatAreaProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether the view is pinned to the bottom. Only auto-scroll while pinned, so
  // streaming tokens don't yank the user back down when they've scrolled up to
  // read earlier content. A ref (not state) avoids a re-render on every scroll.
  const pinnedRef = useRef(true);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  useEffect(() => {
    if (pinnedRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, streamingContent]);

  return (
    <Box
      className="chat-workspace"
      sx={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        height: "auto",
        minHeight: 0,
        width: "100%",
      }}
    >
      <Box
        ref={scrollRef}
        onScroll={handleScroll}
        sx={{ flex: 1, overflow: "auto" }}
      >
        <Box
          className="thread-content"
          sx={{ py: 3, px: "26px", width: "100%" }}
        >
          {messagesLoading && (
            <Box
              role="status"
              sx={{ display: "flex", alignItems: "center", gap: 1, p: 3 }}
            >
              <CircularProgress size={18} />
              <Typography color="text.secondary">
                Loading conversation…
              </Typography>
            </Box>
          )}
          {messagesError && (
            <Alert
              severity="error"
              action={<Button onClick={onRetryMessages}>Retry</Button>}
            >
              Couldn’t load this conversation. {messagesError}
            </Alert>
          )}
          {messages.length === 0 &&
            !isStreaming &&
            !messagesLoading &&
            !messagesError && (
              <Stack
                alignItems="center"
                spacing={2.5}
                sx={{
                  minHeight: "min(480px, 50dvh)",
                  justifyContent: "center",
                  px: { xs: 0, sm: 3 },
                }}
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
                    boxShadow: "none",
                  }}
                >
                  記
                </Box>

                <Stack spacing={0.5} alignItems="center">
                  <Typography
                    variant="overline"
                    sx={{
                      fontFamily: fonts.body,
                      fontSize: "0.875rem",
                      letterSpacing: 0,
                      color: brand.cyan,
                    }}
                  >
                    Ready when you are
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
                    Query your repos and docs, or reach for the web when your
                    corpus doesn't have the answer.
                  </Typography>
                </Stack>

                {/* Suggestion neon cards */}
                <Stack
                  direction="row"
                  flexWrap="wrap"
                  useFlexGap
                  justifyContent="center"
                  sx={{ mt: 1, maxWidth: 600, columnGap: 1, rowGap: 1.25 }}
                >
                  {SUGGESTIONS.map((text) => (
                    <Chip
                      key={text}
                      label={text}
                      variant="outlined"
                      onClick={() => onSend(text)}
                      sx={{
                        fontFamily: fonts.body,
                        fontSize: "0.875rem",
                        borderRadius: "3px",
                        borderColor: `${brand.magenta}55`,
                        color: brand.muted,
                        bgcolor: `${brand.magenta}08`,
                        "&:hover": {
                          bgcolor: `${brand.magenta}18`,
                          borderColor: brand.magenta,
                          color: brand.text,
                          boxShadow: "none",
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
              citations={msg.citations}
              onOpenDocument={onOpenDocument}
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
        disabled={isStreaming || messagesLoading || !!messagesError}
        scope={scope}
        onPickScope={onPickScope}
        onClearScope={onClearScope}
      />
    </Box>
  );
}
