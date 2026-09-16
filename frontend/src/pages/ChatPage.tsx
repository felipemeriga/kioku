import { useState, useRef } from "react";
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

export default function ChatPage() {
  const toast = useToast();
  const { selectedId, messages, setMessages, loadConversations } =
    useConversationsContext();
  const [searchParams, setSearchParams] = useSearchParams();

  const [streamingContent, setStreamingContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentStage, setCurrentStage] = useState<StageEvent | null>(null);
  const streamingRef = useRef("");

  const [scopes, setScopes] = useState<Record<string, ChatScope>>(() =>
    readScopes()
  );
  const [pickerOpen, setPickerOpen] = useState(false);

  // A "Chat with this" navigation from the Documents page pre-scopes the
  // conversation via query params. The scope is DERIVED (no effect needed):
  // URL params win until they're consumed on the first send or scope change.
  const urlFolder = searchParams.get("scope_folder");
  const urlName = searchParams.get("scope_name");
  const urlFile = searchParams.get("scope_file");
  const urlScope: ChatScope | null =
    urlFolder || urlFile
      ? {
          folderId: urlFolder || null,
          folderName: urlName || urlFile || "selection",
          filename: urlFile || null,
        }
      : null;

  const scope: ChatScope | null = selectedId
    ? urlScope ?? scopes[selectedId] ?? null
    : urlScope;

  const applyScope = (conversationId: string, next: ChatScope | null) => {
    const all = readScopes();
    if (next) {
      all[conversationId] = next;
    } else {
      delete all[conversationId];
    }
    localStorage.setItem(SCOPE_STORE_KEY, JSON.stringify(all));
    setScopes(all);
  };

  const setScope = (next: ChatScope | null) => {
    if (selectedId) applyScope(selectedId, next);
    if (urlScope) setSearchParams({}, { replace: true });
  };

  const handleSend = async (
    content: string,
    filters?: ChatFilters,
    fastMode?: boolean
  ) => {
    if (!selectedId || isStreaming) return;

    // Consume a URL-provided scope on first use: persist it to this
    // conversation and clean the address bar.
    if (urlScope) {
      applyScope(selectedId, urlScope);
      setSearchParams({}, { replace: true });
    }

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
