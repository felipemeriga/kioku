import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { useConversations } from "./useConversations";
import { fetchConversations } from "../lib/api";
import type { ReactNode } from "react";

const auth = vi.hoisted(() => ({
  user: null as null | { id: string },
  loading: true,
}));
vi.mock("./useAuth", () => ({ useAuth: () => auth }));
vi.mock("../lib/api", () => ({
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
});
