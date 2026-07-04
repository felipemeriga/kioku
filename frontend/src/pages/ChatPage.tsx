import { useState, useRef } from "react";
import ChatArea from "../components/ChatArea";
import type { Message, ChatFilters, StageEvent } from "../lib/api";
import { streamChat } from "../lib/api";
import { useConversationsContext } from "../hooks/useConversationsContext";
import { useToast, messageFromError } from "../components/ToastProvider";

export default function ChatPage() {
  const toast = useToast();
  const { selectedId, messages, setMessages, loadConversations } =
    useConversationsContext();

  const [streamingContent, setStreamingContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentStage, setCurrentStage] = useState<StageEvent | null>(null);
  const streamingRef = useRef("");

  const handleSend = async (
    content: string,
    filters?: ChatFilters,
    fastMode?: boolean
  ) => {
    if (!selectedId || isStreaming) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setStreamingContent("");
    setCurrentStage(null);
    streamingRef.current = "";

    try {
      await streamChat(
        selectedId,
        content,
        (token) => {
          setCurrentStage(null);
          streamingRef.current += token;
          setStreamingContent(streamingRef.current);
        },
        () => {
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            role: "assistant",
            content: streamingRef.current,
            created_at: new Date().toISOString(),
          };
          setMessages((msgs) => [...msgs, assistantMsg]);
          setStreamingContent("");
          streamingRef.current = "";
          setIsStreaming(false);
          setCurrentStage(null);
          loadConversations();
        },
        filters,
        (stage) => setCurrentStage(stage),
        fastMode
      );
    } catch (err) {
      // Preserve any partial content the assistant already streamed by
      // committing it as a real assistant message with a warning suffix,
      // instead of dropping it silently.
      const partial = streamingRef.current;
      if (partial.length > 0) {
        const truncatedMsg: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            partial +
            "\n\n*(response was truncated: " +
            messageFromError(err, "connection dropped") +
            ")*",
          created_at: new Date().toISOString(),
        };
        setMessages((msgs) => [...msgs, truncatedMsg]);
      }
      toast.showError(err, "Chat failed.");
      setIsStreaming(false);
      setStreamingContent("");
      setCurrentStage(null);
      streamingRef.current = "";
    }
  };

  return (
    <ChatArea
      messages={messages}
      streamingContent={streamingContent}
      isStreaming={isStreaming}
      currentStage={currentStage}
      onSend={handleSend}
    />
  );
}
