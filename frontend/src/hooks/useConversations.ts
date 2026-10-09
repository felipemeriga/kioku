import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Conversation, Message } from "../lib/api";
import {
  fetchConversations,
  createConversation as apiCreateConversation,
  deleteConversation as apiDeleteConversation,
  fetchConversation,
} from "../lib/api";
import { qk } from "../lib/queryKeys";

export function useConversations() {
  const queryClient = useQueryClient();
  // selectedId + messages stay local: messages are both server-loaded AND
  // appended live during the chat SSE stream, which React Query shouldn't own.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);

  const { data: conversations = [], isSuccess } = useQuery({
    queryKey: qk.conversations(),
    queryFn: fetchConversations,
  });

  const loadConversations = useCallback(
    () => queryClient.invalidateQueries({ queryKey: qk.conversations() }),
    [queryClient]
  );

  const createConversation = useCallback(async () => {
    const conv = await apiCreateConversation();
    queryClient.setQueryData<Conversation[]>(qk.conversations(), (prev) => [
      conv,
      ...(prev ?? []),
    ]);
    setSelectedId(conv.id);
    setMessages([]);
    return conv;
  }, [queryClient]);

  // Auto-select the first conversation, or create one for a brand-new user so
  // the chat is immediately usable (#90). Runs once after the list first loads.
  const didInitRef = useRef(false);
  useEffect(() => {
    if (!isSuccess || didInitRef.current) return;
    didInitRef.current = true;
    void (async () => {
      if (conversations.length > 0) {
        setSelectedId(conversations[0].id);
      } else {
        try {
          await createConversation();
        } catch {
          /* leave unselected; the next send retries via ChatPage */
        }
      }
    })();
  }, [isSuccess, conversations, createConversation]);

  // Rename-from-sidebar dispatches conversations-changed → refetch the list.
  useEffect(() => {
    const handler = () => {
      void queryClient.invalidateQueries({ queryKey: qk.conversations() });
    };
    window.addEventListener("conversations-changed", handler);
    return () => window.removeEventListener("conversations-changed", handler);
  }, [queryClient]);

  // Load messages for the selected conversation; chat streaming then appends
  // to this local state live via setMessages.
  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    fetchConversation(selectedId).then((conv) => {
      if (!active) return;
      setMessages(conv.messages);
    });
    return () => {
      active = false;
    };
  }, [selectedId]);

  const selectConversation = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const removeConversation = useCallback(
    async (id: string) => {
      await apiDeleteConversation(id);
      const prev =
        queryClient.getQueryData<Conversation[]>(qk.conversations()) ?? [];
      const remaining = prev.filter((c) => c.id !== id);
      queryClient.setQueryData(qk.conversations(), remaining);
      if (selectedId === id) {
        const next = remaining.length > 0 ? remaining[0].id : null;
        setSelectedId(next);
        if (!next) setMessages([]);
      }
    },
    [queryClient, selectedId]
  );

  return {
    conversations,
    selectedId,
    messages,
    setMessages,
    selectConversation,
    loadConversations,
    createConversation,
    removeConversation,
  };
}
