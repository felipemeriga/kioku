import { useState, useEffect, useCallback } from "react";
import type { Conversation, Message } from "../lib/api";
import {
  fetchConversations,
  createConversation as apiCreateConversation,
  deleteConversation as apiDeleteConversation,
  fetchConversation,
} from "../lib/api";

export function useConversations() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [initialized, setInitialized] = useState(false);

  const loadConversations = useCallback(async () => {
    const convs = await fetchConversations();
    setConversations(convs);
    return convs;
  }, []);

  // Initial load - subscribe to external data
  useEffect(() => {
    let active = true;
    fetchConversations().then((convs) => {
      if (!active) return;
      setConversations(convs);
      if (convs.length > 0) {
        setSelectedId(convs[0].id);
      }
      setInitialized(true);
    });
    return () => { active = false; };
  }, []);

  // React to external mutations (e.g. rename from the sidebar row).
  useEffect(() => {
    const handler = () => {
      fetchConversations().then(setConversations).catch(() => {});
    };
    window.addEventListener("conversations-changed", handler);
    return () => window.removeEventListener("conversations-changed", handler);
  }, []);

  // Load messages when selectedId changes
  useEffect(() => {
    if (!initialized) return;
    if (!selectedId) return;

    let active = true;
    fetchConversation(selectedId).then((conv) => {
      if (!active) return;
      setMessages(conv.messages);
    });
    return () => { active = false; };
  }, [selectedId, initialized]);

  const selectConversation = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const createConversation = useCallback(async () => {
    const conv = await apiCreateConversation();
    setConversations((prev) => [conv, ...prev]);
    setSelectedId(conv.id);
    setMessages([]);
  }, []);

  const removeConversation = useCallback(
    async (id: string) => {
      await apiDeleteConversation(id);
      setConversations((prev) => {
        const remaining = prev.filter((c) => c.id !== id);
        if (selectedId === id) {
          const next = remaining.length > 0 ? remaining[0].id : null;
          setSelectedId(next);
          if (!next) setMessages([]);
        }
        return remaining;
      });
    },
    [selectedId]
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
