import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/renderWithProviders";
import ChatPage from "./ChatPage";
import type { NativeChatExecution } from "../lib/api";

const state = vi.hoisted(() => ({
  selectedId: "conversation",
  messages: [
    {
      id: "saved",
      role: "user",
      content: "Original saved question",
      created_at: "now",
    },
  ],
  user: { id: "owner" } as { id: string } | null,
  activeExecution: null as NativeChatExecution | null,
  stream: vi.fn(),
  cancel: vi.fn(),
  retry: vi.fn(),
  setMessages: vi.fn(),
}));
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
vi.mock("../lib/api", async (original) => ({
  ...(await original<typeof import("../lib/api")>()),
  streamChat: state.stream,
  cancelChatExecution: state.cancel,
}));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: state.user }) }));
vi.mock("../hooks/useConversationsContext", () => ({
  useConversationsContext: () => ({
    selectedId: state.selectedId,
    activeExecution: state.activeExecution,
    messages: state.messages,
    messagesLoading: false,
    conversationsLoading: false,
    messagesError: null,
    retryMessages: state.retry,
    setMessages: state.setMessages,
    loadConversations: vi.fn(),
    createConversation: vi.fn(),
  }),
}));
vi.mock("../components/ChatArea", () => ({
  default: (p: {
    isStreaming: boolean;
    restoredSettings?: { model: string; mode: string };
  }) => (
    <div>
      {p.isStreaming ? "Streaming saved job" : "Settled"}
      <span>
        {p.restoredSettings?.model}/{p.restoredSettings?.mode}
      </span>
    </div>
  ),
}));
vi.mock("../components/ScopePickerDialog", () => ({ default: () => null }));
vi.mock("../components/DocumentViewerDrawer", () => ({ default: () => null }));
const execution: NativeChatExecution = {
  turn_id: "turn",
  job_id: "job",
  conversation_id: "conversation",
  model: "sonnet",
  mode: "plain",
};
beforeEach(() => {
  state.selectedId = "conversation";
  state.messages = [
    {
      id: "saved",
      role: "user",
      content: "Original saved question",
      created_at: "now",
    },
  ];
  state.user = { id: "owner" };
  state.activeExecution = null;
  state.stream.mockReset();
  state.cancel.mockReset();
  state.cancel.mockResolvedValue(undefined);
  state.retry.mockReset();
  state.setMessages.mockReset();
  state.stream.mockImplementation(() => new Promise<void>(() => {}));
});

it("discovers an old orphan after async history hydration, restores profile and cancels its accepted job", async () => {
  const view = renderWithProviders(<ChatPage />);
  expect(state.stream).not.toHaveBeenCalled();
  state.activeExecution = execution;
  view.rerender(<ChatPage />);
  await waitFor(() => expect(state.stream).toHaveBeenCalledTimes(1));
  const args = state.stream.mock.calls[0];
  expect(args[0]).toBe("conversation");
  expect(args[1]).toBe("");
  expect(args[6]).toBe("sonnet");
  expect(args[7]).toBe("plain");
  expect(args[16]).toEqual(execution);
  expect(screen.getByText("sonnet/plain")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cancel generation" }));
  expect(state.cancel).toHaveBeenCalledWith("job");
  await act(async () => args[3]());
  expect(state.retry).toHaveBeenCalledTimes(1);
  expect(state.setMessages).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "Cancel generation" }),
  ).not.toBeInTheDocument();
});

it("aborts only the listener on switch/logout and reattaches when returning to the same job", async () => {
  state.activeExecution = execution;
  const view = renderWithProviders(<ChatPage />);
  await waitFor(() => expect(state.stream).toHaveBeenCalledTimes(1));
  const signal = state.stream.mock.calls[0][17] as AbortSignal;
  state.selectedId = "other";
  view.rerender(<ChatPage />);
  expect(signal.aborted).toBe(true);
  expect(state.cancel).not.toHaveBeenCalled();
  state.selectedId = "conversation";
  view.rerender(<ChatPage />);
  await waitFor(() => expect(state.stream).toHaveBeenCalledTimes(2));
  state.user = null;
  view.rerender(<ChatPage />);
  expect((state.stream.mock.calls[1][17] as AbortSignal).aborted).toBe(true);
});

it("does not treat StrictMode listener cleanup as a terminal model outcome", async () => {
  state.activeExecution = execution;
  renderWithProviders(
    <StrictMode>
      <ChatPage />
    </StrictMode>,
  );
  await waitFor(() =>
    expect(
      state.stream.mock.calls.filter(
        (call) => !(call[17] as AbortSignal).aborted,
      ),
    ).toHaveLength(1),
  );
  expect(state.cancel).not.toHaveBeenCalled();
});

it("shows terminal recovery failure once without an automatic reattach loop", async () => {
  state.activeExecution = execution;
  state.stream.mockRejectedValueOnce(new Error("quota_limited"));
  const view = renderWithProviders(<ChatPage />);
  await waitFor(() => expect(state.retry).toHaveBeenCalledTimes(1));
  state.activeExecution = { ...execution };
  view.rerender(<ChatPage />);
  await act(async () => {});
  expect(state.stream).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("button", { name: "Cancel generation" }),
  ).not.toBeInTheDocument();
});

it("offers explicit uncertain recovery only after the exact accepted user message hydrates", async () => {
  state.activeExecution = {
    ...execution,
    state: "uncertain",
    user_message_id: "saved",
    scope_folder_id: "original-folder",
    scope_filename: "original-guide.md",
  };
  state.messages = [
    {
      id: "newer",
      role: "user",
      content: "Unrelated later question",
      created_at: "later",
    },
  ];
  state.stream.mockRejectedValueOnce(new Error("execution_uncertain"));
  const view = renderWithProviders(<ChatPage />);
  await waitFor(() => expect(state.retry).toHaveBeenCalledTimes(1));
  expect(state.stream).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("button", { name: "Rebuild context and retry" }),
  ).not.toBeInTheDocument();
  state.messages = [
    {
      id: "saved",
      role: "user",
      content: "Original saved question",
      created_at: "now",
    },
    ...state.messages,
  ];
  view.rerender(<ChatPage />);
  const rebuild = await screen.findByRole("button", {
    name: "Rebuild context and retry",
  });
  expect(state.stream).toHaveBeenCalledTimes(1);
  fireEvent.click(rebuild);
  await waitFor(() => expect(state.stream).toHaveBeenCalledTimes(2));
  const args = state.stream.mock.calls[1];
  expect(args[1]).toBe("Original saved question");
  expect(args[4]).toEqual({
    scopeFolderId: "original-folder",
    scopeFilename: "original-guide.md",
  });
  expect(args[6]).toBe("sonnet");
  expect(args[7]).toBe("plain");
  expect(args[15]).toBe(true);
});

it("waits for authoritative terminal state when replay disconnects from a submitted job", async () => {
  state.activeExecution = {
    ...execution,
    state: "submitted",
    user_message_id: "saved",
  };
  state.stream.mockRejectedValueOnce(new Error("connection ended"));
  const view = renderWithProviders(<ChatPage />);
  await waitFor(() => expect(state.retry).toHaveBeenCalledTimes(1));
  expect(
    screen.queryByRole("button", { name: "Rebuild context and retry" }),
  ).not.toBeInTheDocument();
  state.activeExecution = { ...state.activeExecution, state: "uncertain" };
  view.rerender(<ChatPage />);
  expect(
    await screen.findByRole("button", { name: "Rebuild context and retry" }),
  ).toBeInTheDocument();
  expect(state.stream).toHaveBeenCalledTimes(1);
});
