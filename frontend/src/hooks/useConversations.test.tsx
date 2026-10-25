import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useConversations } from "./useConversations";
import { fetchConversations, fetchConversation } from "../lib/api";
import type { ReactNode } from "react";

const auth = vi.hoisted(() => ({
  user: null as null | { id: string },
  loading: true,
}));
vi.mock("./useAuth", () => ({ useAuth: () => auth }));
vi.mock("../lib/api", () => ({
  ApiError: class ApiError extends Error {
    userMessage = "Request failed";
  },
  fetchConversations: vi.fn(async () => [
    {
      id: "existing-history",
      title: "Stored conversation",
      created_at: "2026-10-01",
      updated_at: "2026-10-22",
    },
  ]),
  fetchConversation: vi.fn(async () => ({
    messages: [{ role: "user", content: "Existing message" }],
  })),
  createConversation: vi.fn(),
  deleteConversation: vi.fn(),
}));

describe("authenticated conversation history", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.user = null;
    auth.loading = true;
  });
  it("waits for session hydration then loads stored history after the auth cache reset", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(() => useConversations(), {
      wrapper,
    });
    await act(async () => {});
    expect(fetchConversations).not.toHaveBeenCalled();
    act(() => {
      client.clear();
      auth.user = { id: "owner" };
      auth.loading = false;
      rerender();
    });
    await waitFor(() =>
      expect(result.current.conversations[0]?.id).toBe("existing-history")
    );
    await waitFor(() =>
      expect(result.current.messages[0]?.content).toBe("Existing message")
    );
    expect(fetchConversations).toHaveBeenCalledTimes(1);
    client.clear();
  });
  it("reports a failed message read and reloads the existing conversation on retry", async () => {
    auth.user = { id: "owner" };
    auth.loading = false;
    const messages = vi.mocked(fetchConversation);
    messages.mockRejectedValueOnce(new Error("offline"));
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useConversations(), { wrapper });
    await waitFor(() => expect(result.current.messagesError).toBe("offline"));
    expect(result.current.messages).toEqual([]);
    act(() => result.current.retryMessages());
    await waitFor(() =>
      expect(result.current.messages[0]?.content).toBe("Existing message")
    );
    expect(result.current.messagesError).toBeNull();
    client.clear();
  });
});
