import { useState, useRef, useEffect } from "react";
import { Box, Button, Typography } from "@mui/material";
import { useSearchParams } from "react-router-dom";
import ChatArea from "../components/ChatArea";
import ScopePickerDialog from "../components/ScopePickerDialog";
import type {
  Message,
  ChatFilters,
  ChatMode,
  ChatModel,
  ChatScope,
  Citation,
  DebugTrace,
  StageEvent,
} from "../lib/api";
import {
  streamChat,
  cancelChatExecution,
  requiresNativeRebuild,
} from "../lib/api";
import DocumentViewerDrawer from "../components/DocumentViewerDrawer";
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
  const {
    selectedId,
    conversationsLoading,
    messages,
    messagesLoading,
    messagesError,
    retryMessages,
    setMessages,
    loadConversations,
    createConversation,
  } = useConversationsContext();
  const [searchParams, setSearchParams] = useSearchParams();

  const [streamingContent, setStreamingContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamConversationId, setStreamConversationId] = useState<
    string | null
  >(null);
  const selectedConversation = useRef(selectedId);
  const activeRequest = useRef<string | null>(null);
  useEffect(() => {
    selectedConversation.current = selectedId;
  }, [selectedId]);
  const displayingStream = isStreaming && streamConversationId === selectedId;
  const [currentStage, setCurrentStage] = useState<StageEvent | null>(null);
  const streamingRef = useRef("");
  const activeJob = useRef<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [liveTools, setLiveTools] = useState<
    Record<string, { name: string; status: string; sources?: number }>
  >({});
  const [recovery, setRecovery] = useState<{
    conversationId: string;
    content: string;
    filters?: ChatFilters;
    model?: ChatModel;
    mode?: ChatMode;
    debug?: boolean;
  } | null>(null);

  const [scopes, setScopes] = useState<Record<string, ChatScope>>(() =>
    readScopes(),
  );
  const [pickerOpen, setPickerOpen] = useState(false);

  // Document citation clicks open the same in-app viewer the Documents page uses.
  const [viewerFile, setViewerFile] = useState<string | null>(null);
  const [viewerFolder, setViewerFolder] = useState<string | null>(null);
  const openDocument = (filename: string, folderId?: string | null) => {
    setViewerFolder(folderId ?? null);
    setViewerFile(filename);
  };

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
    ? (urlScope ?? scopes[selectedId] ?? null)
    : urlScope;

  const applyScope = (conversationId: string, next: ChatScope | null) => {
    const all = readScopes();
    if (next) {
      all[conversationId] = next;
    } else {
      delete all[conversationId];
    }
    try {
      localStorage.setItem(SCOPE_STORE_KEY, JSON.stringify(all));
    } catch {
      // Browser storage policies must not prevent a scoped chat from being sent.
    }
    setScopes(all);
  };

  const setScope = (next: ChatScope | null) => {
    if (selectedId) applyScope(selectedId, next);
    if (urlScope) setSearchParams({}, { replace: true });
  };

  const handleSend = async (
    content: string,
    filters?: ChatFilters,
    model?: ChatModel,
    mode?: ChatMode,
    debug?: boolean,
    rebuild = false,
  ) => {
    if (displayingStream) return;

    // A brand-new user may not have a conversation yet. Create one on first
    // send instead of silently dropping the message — the old `!selectedId`
    // guard made the very first send a no-op with no feedback.
    let convId = selectedId;
    if (!convId) {
      try {
        const conv = await createConversation();
        convId = conv.id;
      } catch (err) {
        toast.showError(err, "Couldn't start a conversation.");
        return;
      }
    }

    // Consume a URL-provided scope on first use: persist it to this
    // conversation and clean the address bar.
    if (urlScope) {
      applyScope(convId, urlScope);
      setSearchParams({}, { replace: true });
    }

    const requestId = crypto.randomUUID();
    activeRequest.current = requestId;
    setStreamConversationId(convId);

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
    activeJob.current = null;
    setActiveJobId(null);
    setLiveTools({});
    setRecovery(null);
    // Debug trace and citations arrive just before 'done'; hold them until we
    // build the committed assistant message.
    let debugTrace: DebugTrace | undefined;
    let citations: Citation[] | undefined;

    const scopedFilters: ChatFilters | undefined = scope
      ? {
          ...(filters ?? {}),
          scopeFolderId: scope.folderId,
          scopeFilename: scope.filename ?? null,
        }
      : filters;

    try {
      await streamChat(
        convId,
        content,
        (token) => {
          if (activeRequest.current !== requestId) return;
          streamingRef.current += token;
          setStreamingContent(streamingRef.current);
        },
        () => {
          if (activeRequest.current !== requestId) return;
          const assistantMsg: Message = {
            id: crypto.randomUUID(),
            role: "assistant",
            content: streamingRef.current,
            created_at: new Date().toISOString(),
            debug: debugTrace,
            citations,
          };
          if (selectedConversation.current === convId)
            setMessages((msgs) => [...msgs, assistantMsg]);
          setStreamingContent("");
          streamingRef.current = "";
          setIsStreaming(false);
          setCurrentStage(null);
          loadConversations();
        },
        scopedFilters,
        (stage) => {
          if (activeRequest.current === requestId) setCurrentStage(stage);
        },
        model,
        mode,
        debug,
        (trace) => {
          debugTrace = trace;
        },
        undefined,
        (cites) => {
          citations = cites;
        },
        (text) => {
          if (activeRequest.current !== requestId) return;
          streamingRef.current = text;
          setStreamingContent(text);
        },
        (jobId) => {
          if (activeRequest.current !== requestId) return;
          activeJob.current = jobId;
          setActiveJobId(jobId);
        },
        (event) => {
          if (activeRequest.current !== requestId) return;
          if (
            typeof event.tool_call_id !== "string" ||
            typeof event.name !== "string"
          )
            return;
          const id = event.tool_call_id;
          const name = event.name;
          setLiveTools((previous) => ({
            ...previous,
            [id]: {
              name,
              status:
                typeof event.status === "string" ? event.status : "running",
              sources: Array.isArray(event.sources)
                ? event.sources.length
                : previous[id]?.sources,
            },
          }));
        },
        rebuild,
      );
    } catch (err) {
      if (activeRequest.current !== requestId) return;
      // Preserve any partial content the assistant already streamed by
      // committing it as a real assistant message with a warning suffix,
      // instead of dropping it silently.
      if (activeJob.current || requiresNativeRebuild(err))
        setRecovery({
          conversationId: convId,
          content,
          filters: scopedFilters,
          model,
          mode,
          debug,
        });
      const partial = streamingRef.current;
      if (
        partial.length > 0 &&
        !activeJob.current &&
        selectedConversation.current === convId
      ) {
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
      {recovery &&
        recovery.conversationId === selectedId &&
        !displayingStream && (
          <Box sx={{ p: 2 }}>
            <Typography sx={{ fontSize: 13, mb: 1 }}>
              Retry this request in a fresh native session using saved
              conversation history.
            </Typography>
            <Button
              variant="outlined"
              size="small"
              onClick={() =>
                void handleSend(
                  recovery.content,
                  recovery.filters,
                  recovery.model,
                  recovery.mode,
                  recovery.debug,
                  true,
                )
              }
            >
              Rebuild context and retry
            </Button>
          </Box>
        )}
      {displayingStream && Object.keys(liveTools).length > 0 && (
        <Box role="log" aria-label="Agent execution" sx={{ px: 2, py: 1 }}>
          {Object.entries(liveTools).map(([id, tool], index) => (
            <Typography key={id} sx={{ fontSize: 13 }}>
              {index + 1}. {tool.name} · {tool.status}
              {tool.sources !== undefined ? ` · ${tool.sources} sources` : ""}
            </Typography>
          ))}
        </Box>
      )}
      {displayingStream && activeJobId && (
        <Button
          size="small"
          variant="outlined"
          onClick={() => {
            void cancelChatExecution(activeJob.current!).catch((error) =>
              toast.showError(error, "Cancellation failed"),
            );
          }}
          sx={{ alignSelf: "flex-end", m: "8px 16px" }}
        >
          Cancel generation
        </Button>
      )}
      <ChatArea
        conversationId={selectedId}
        messages={messages}
        messagesLoading={
          messagesLoading || (conversationsLoading && !selectedId)
        }
        messagesError={messagesError}
        onRetryMessages={retryMessages}
        streamingContent={displayingStream ? streamingContent : ""}
        isStreaming={displayingStream}
        currentStage={displayingStream ? currentStage : null}
        onSend={handleSend}
        scope={scope}
        onPickScope={() => setPickerOpen(true)}
        onClearScope={() => setScope(null)}
        onOpenDocument={openDocument}
      />
      <DocumentViewerDrawer
        filename={viewerFile}
        folderId={viewerFolder}
        onClose={() => setViewerFile(null)}
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
