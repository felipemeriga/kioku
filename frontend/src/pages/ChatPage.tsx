import { useEffect, useState, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import ChatArea from "../components/ChatArea";
import ScopePickerDialog from "../components/ScopePickerDialog";
import type { Message, ChatFilters, ChatScope, StageEvent } from "../lib/api";
import { streamChat } from "../lib/api";
import { useConversationsContext } from "../hooks/useConversationsContext";
import { useToast, messageFromError } from "../components/ToastProvider";

const SCOPE_STORE_KEY = "kioku.chat.scopes";

/** Per-conversation scope persistence: { [conversationId]: ChatScope }. */
function readScopes(): Record<string, ChatScope> {
  try {
    return JSON.parse(localStorage.getItem(SCOPE_STORE_KEY) || "{}");
  } catch {
    return {};
  }
}

function persistScope(conversationId: string, scope: ChatScope | null) {
  const all = readScopes();
  if (scope) {
    all[conversationId] = scope;
  } else {
    delete all[conversationId];
  }
  localStorage.setItem(SCOPE_STORE_KEY, JSON.stringify(all));
}

export default function ChatPage() {
  const toast = useToast();
  const { selectedId, messages, setMessages, loadConversations } =
    useConversationsContext();
  const [searchParams, setSearchParams] = useSearchParams();

  const [streamingContent, setStreamingContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentStage, setCurrentStage] = useState<StageEvent | null>(null);
  const streamingRef = useRef("");

  const [scope, setScopeState] = useState<ChatScope | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Load the persisted scope when the conversation changes.
  useEffect(() => {
    if (!selectedId) {
      setScopeState(null);
      return;
    }
    setScopeState(readScopes()[selectedId] ?? null);
  }, [selectedId]);

  // A "Chat with this" navigation from the Documents page pre-scopes the
  // conversation via query params; consume them once and clean the URL.
  useEffect(() => {
    const folderId = searchParams.get("scope_folder");
    const folderName = searchParams.get("scope_name");
    const filename = searchParams.get("scope_file");
    if (!selectedId || (!folderId && !filename)) return;
    const incoming: ChatScope = {
      folderId: folderId || null,
      folderName: folderName || filename || "selection",
      filename: filename || null,
    };
    setScopeState(incoming);
    persistScope(selectedId, incoming);
    setSearchParams({}, { replace: true });
  }, [selectedId, searchParams, setSearchParams]);

  const setScope = (next: ChatScope | null) => {
    setScopeState(next);
    if (selectedId) persistScope(selectedId, next);
  };

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

    const scopedFilters: ChatFilters | undefined = scope
      ? {
          ...(filters ?? {}),
          scopeFolderId: scope.filename ? null : scope.folderId,
          scopeFilename: scope.filename ?? null,
        }
      : filters;

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
        scopedFilters,
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
    <>
      <ChatArea
        messages={messages}
        streamingContent={streamingContent}
        isStreaming={isStreaming}
        currentStage={currentStage}
        onSend={handleSend}
        scope={scope}
        onPickScope={() => setPickerOpen(true)}
        onClearScope={() => setScope(null)}
      />
      <ScopePickerDialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={(next) => {
          setScope(next);
          setPickerOpen(false);
        }}
      />
    </>
  );
}
