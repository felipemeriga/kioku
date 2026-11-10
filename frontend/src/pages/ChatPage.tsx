import { useState, useRef, useEffect, useEffectEvent } from "react";
import { Box, Button, Typography } from "@mui/material";
import { useSearchParams } from "react-router-dom";
import ChatArea from "../components/ChatArea";
import ScopePickerDialog from "../components/ScopePickerDialog";
import type {
  Message,
  ChatFilters,
  ChatMode,
  ReasoningEffort,
  ChatModel,
  ChatScope,
  Citation,
  DebugTrace,
  StageEvent,
  NativeChatExecution,
} from "../lib/api";
import {
  streamChat,
  ApiError,
  cancelChatExecution,
  requiresNativeRebuild,
} from "../lib/api";
import DocumentViewerDrawer from "../components/DocumentViewerDrawer";
import { useConversationsContext } from "../hooks/useConversationsContext";
import { useAuth } from "../hooks/useAuth";
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
  const { user } = useAuth();
  const {
    selectedId,
    activeExecution,
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
  const sendController = useRef<AbortController | null>(null);
  const recoveredJobs = useRef(new Set<string>());
  useEffect(
    () => () => {
      sendController.current?.abort();
      activeRequest.current = null;
    },
    [user?.id]
  );
  useEffect(() => {
    selectedConversation.current = selectedId;
  }, [selectedId]);
  const displayingStream = isStreaming && streamConversationId === selectedId;
  const [currentStage, setCurrentStage] = useState<StageEvent | null>(null);
  const streamingRef = useRef("");
  const revealedRef = useRef("");
  const revealFrame = useRef<number | null>(null);
  const revealTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const revealTick = useRef(0);
  const stopReveal = () => {
    if (revealFrame.current !== null) cancelAnimationFrame(revealFrame.current);
    if (revealTimer.current !== null) clearTimeout(revealTimer.current);
    revealFrame.current = null;
    revealTimer.current = null;
    revealTick.current = 0;
  };
  const revealText = (text: string) => {
    if (!text.startsWith(revealedRef.current)) revealedRef.current = "";
    if (revealFrame.current !== null) return;
    const tick = (time: number) => {
      const elapsed = revealTick.current ? time - revealTick.current : 16;
      revealTick.current = time;
      const next = Math.min(
        streamingRef.current.length,
        revealedRef.current.length + Math.max(1, Math.ceil(elapsed * 0.65))
      );
      revealedRef.current = streamingRef.current.slice(0, next);
      setStreamingContent(revealedRef.current);
      revealFrame.current =
        next < streamingRef.current.length ? requestAnimationFrame(tick) : null;
    };
    revealFrame.current = requestAnimationFrame(tick);
  };
  const finishReveal = (done: () => void) => {
    const remaining = streamingRef.current.length - revealedRef.current.length;
    if (remaining <= 0) {
      stopReveal();
      done();
      return;
    }
    // Keep the canonical response immediate in state; only the visual reveal
    // gets a short grace period after the final network frame.
    revealTimer.current = setTimeout(() => {
      stopReveal();
      revealedRef.current = streamingRef.current;
      setStreamingContent(streamingRef.current);
      done();
    }, Math.min(1600, Math.ceil(remaining / 0.65)));
  };
  useEffect(() => () => stopReveal(), []);
  const activeJob = useRef<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [liveTools, setLiveTools] = useState<
    Record<string, { name: string; status: string; sources?: number }>
  >({});
  const [pendingRecovery, setPendingRecovery] = useState<{
    ownerId: string;
    execution: NativeChatExecution;
    allowRebuild: boolean;
  } | null>(null);
  const [recovery, setRecovery] = useState<{
    conversationId: string;
    content: string;
    filters?: ChatFilters;
    model?: ChatModel;
    mode?: ChatMode;
    debug?: boolean;
    effort?: ReasoningEffort;
  } | null>(null);

  const [scopes, setScopes] = useState<Record<string, ChatScope>>(() =>
    readScopes()
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
    ? urlScope ?? scopes[selectedId] ?? null
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
    effort?: ReasoningEffort,
    rebuild = false
  ) => {
    if (displayingStream) return;

    setIsStreaming(true);
    setStreamConversationId(selectedId);
    setCurrentStage({ stage: "thinking", detail: "Preparing your answer" });

    // A brand-new user may not have a conversation yet. Create one on first
    // send instead of silently dropping the message — the old `!selectedId`
    // guard made the very first send a no-op with no feedback.
    let convId = selectedId;
    if (!convId) {
      try {
        const conv = await createConversation();
        convId = conv.id;
      } catch (err) {
        setIsStreaming(false);
        setCurrentStage(null);
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
    const controller = new AbortController();
    sendController.current = controller;
    setStreamConversationId(convId);

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    if (!rebuild) setMessages((prev) => [...prev, userMsg]);
    setIsStreaming(true);
    setStreamingContent("");
    stopReveal();
    revealedRef.current = "";
    setCurrentStage({ stage: "thinking", detail: "Preparing your answer" });
    streamingRef.current = "";
    activeJob.current = null;
    setActiveJobId(null);
    setLiveTools({});
    setRecovery(null);
    setPendingRecovery(null);
    // Debug trace and citations arrive just before 'done'; hold them until we
    // build the committed assistant message.
    let debugTrace: DebugTrace | undefined;
    let citations: Citation[] | undefined;

    const scopedFilters: ChatFilters | undefined = rebuild
      ? filters
      : scope
      ? {
          ...(filters ?? {}),
          scopeFolderId: scope.folderId,
          scopeFilename: scope.filename ?? null,
        }
      : filters;

    const runRequest = (rebuildContext: boolean) =>
      streamChat(
        convId,
        content,
        (token) => {
          if (activeRequest.current !== requestId) return;
          streamingRef.current += token;
          revealText(streamingRef.current);
        },
        () => {
          if (activeRequest.current !== requestId) return;
          finishReveal(() => {
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
            activeRequest.current = null;
          });
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
          revealText(text);
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
        rebuildContext,
        undefined,
        controller.signal,
        effort
      );
    try {
      try {
        await runRequest(rebuild);
      } catch (error) {
        const code =
          error instanceof ApiError
            ? (error.detail as { code?: string } | undefined)?.code
            : undefined;
        if (
          !rebuild &&
          code === "conversation_policy_changed" &&
          !activeJob.current &&
          !streamingRef.current &&
          !controller.signal.aborted &&
          activeRequest.current === requestId
        ) {
          setCurrentStage({
            stage: "thinking",
            detail: "Restoring saved conversation context",
          });
          await runRequest(true);
        } else {
          throw error;
        }
      }
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
          effort,
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
      stopReveal();
      revealedRef.current = "";
      setCurrentStage(null);
      streamingRef.current = "";
      activeRequest.current = null;
    }
  };

  const resumeExecution = useEffectEvent(
    async (
      execution: NativeChatExecution,
      controller: AbortController,
      requestId: string,
      settled: () => void
    ) => {
      const current = () =>
        !controller.signal.aborted && activeRequest.current === requestId;
      setStreamConversationId(execution.conversation_id);
      setIsStreaming(true);
      setStreamingContent("");
      streamingRef.current = "";
      activeJob.current = execution.job_id;
      setActiveJobId(execution.job_id);
      setLiveTools({});
      setCurrentStage({
        stage: "thinking",
        detail: "Reconnecting to the saved execution…",
      });
      try {
        await streamChat(
          execution.conversation_id,
          "",
          (token) => {
            if (!current()) return;
            streamingRef.current += token;
            setStreamingContent(streamingRef.current);
          },
          () => {
            if (!current()) return;
            settled();
            setIsStreaming(false);
            // The backend committed the canonical message; never append a duplicate replay.
            retryMessages();
            void loadConversations();
          },
          undefined,
          (stage) => {
            if (current()) setCurrentStage(stage);
          },
          execution.model,
          execution.mode,
          true,
          undefined,
          undefined,
          undefined,
          (text) => {
            if (current()) {
              streamingRef.current = text;
              setStreamingContent(text);
            }
          },
          (job) => {
            if (current()) {
              activeJob.current = job;
              setActiveJobId(job);
            }
          },
          (event) => {
            if (
              !current() ||
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
          false,
          execution,
          controller.signal,
          execution.reasoning_effort ??
            (execution.mode === "deep" ? "high" : "low")
        );
      } catch (error) {
        if (current()) {
          settled();
          setIsStreaming(false);
          if (user?.id) {
            setPendingRecovery({
              ownerId: user.id,
              execution,
              allowRebuild:
                execution.state === "uncertain" ||
                execution.state === "failed" ||
                execution.state === "cancelled" ||
                requiresNativeRebuild(error),
            });
          }
          toast.showError(error, "Could not recover the saved execution.");
          retryMessages();
        }
      } finally {
        if (current()) {
          activeRequest.current = null;
          setIsStreaming(false);
          setStreamingContent("");
          streamingRef.current = "";
          setCurrentStage(null);
        }
      }
    }
  );
  const offerPendingRecovery = useEffectEvent(() => {
    if (
      !pendingRecovery ||
      pendingRecovery.ownerId !== user?.id ||
      pendingRecovery.execution.conversation_id !== selectedId
    )
      return;
    const execution = pendingRecovery.execution;
    const latestState =
      activeExecution?.job_id === execution.job_id
        ? activeExecution.state
        : undefined;
    if (
      !pendingRecovery.allowRebuild &&
      latestState !== "failed" &&
      latestState !== "uncertain" &&
      latestState !== "cancelled"
    )
      return;
    const message = messages.find(
      (row) => row.id === execution.user_message_id && row.role === "user"
    );
    if (!message) return;
    setRecovery({
      conversationId: execution.conversation_id,
      content: message.content,
      filters: {
        scopeFolderId: execution.scope_folder_id ?? null,
        scopeFilename: execution.scope_filename ?? null,
      },
      model: execution.model,
      mode: execution.mode,
      effort:
        execution.reasoning_effort ??
        (execution.mode === "deep" ? "high" : "low"),
      debug: true,
    });
    setPendingRecovery(null);
  });
  useEffect(() => {
    offerPendingRecovery();
  }, [messages, pendingRecovery, selectedId, user?.id, activeExecution]);
  useEffect(() => {
    if (
      !user?.id ||
      !activeExecution ||
      activeExecution.conversation_id !== selectedId ||
      activeRequest.current ||
      recoveredJobs.current.has(`${user.id}:${activeExecution.job_id}`)
    )
      return;
    const key = `${user.id}:${activeExecution.job_id}`;
    const jobs = recoveredJobs.current;
    jobs.add(key);
    let settled = false;
    const controller = new AbortController();
    const requestId = crypto.randomUUID();
    activeRequest.current = requestId;
    void resumeExecution(activeExecution, controller, requestId, () => {
      settled = true;
    });
    return () => {
      controller.abort(); // Disconnect only; the accepted model execution remains durable.
      if (!settled) jobs.delete(key);
      if (activeRequest.current === requestId) activeRequest.current = null;
    };
  }, [selectedId, user?.id, activeExecution]);

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
                  recovery.effort,
                  true
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
              toast.showError(error, "Cancellation failed")
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
        restoredSettings={
          activeExecution && activeExecution.conversation_id === selectedId
            ? activeExecution
            : undefined
        }
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
