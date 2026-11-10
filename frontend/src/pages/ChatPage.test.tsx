import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import ChatPage from "./ChatPage";
import { ApiError, type NativeChatExecution } from "../lib/api";

const fixtures = vi.hoisted(() => ({
  stream: vi.fn(),
  execution: undefined as NativeChatExecution | undefined,
  messages: [
    {
      id: "saved",
      role: "assistant",
      content: "Previously saved history",
      created_at: "now",
    },
  ],
  setMessages: vi.fn(),
}));
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
vi.mock("../lib/api", async (original) => ({
  ...(await original<typeof import("../lib/api")>()),
  streamChat: fixtures.stream,
}));
vi.mock("../hooks/useConversationsContext", () => ({
  useConversationsContext: () => ({
    selectedId: "conversation",
    activeExecution: fixtures.execution,
    messages: fixtures.messages,
    setMessages: fixtures.setMessages,
    conversationsLoading: false,
    messagesLoading: false,
    messagesError: null,
    retryMessages: vi.fn(),
    loadConversations: vi.fn(),
    createConversation: vi.fn(),
  }),
}));
vi.mock("../components/ChatArea", () => ({
  default: (props: {
    onSend: (...args: unknown[]) => void;
    currentStage?: { detail?: string };
    streamingContent?: string;
  }) => (
    <>
      <span>{props.currentStage?.detail}</span>
      <span data-testid="streaming-answer">{props.streamingContent}</span>
      <button
        onClick={() =>
          props.onSend(
            "Follow-up question",
            undefined,
            "sonnet",
            "agentic",
            true,
            "high",
          )
        }
      >
        Send selected mode
      </button>
    </>
  ),
}));
vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: { id: "owner" } }),
}));
vi.mock("../components/ScopePickerDialog", () => ({ default: () => null }));
vi.mock("../components/DocumentViewerDrawer", () => ({ default: () => null }));

afterEach(() => vi.unstubAllGlobals());

beforeEach(() => {
  fixtures.stream.mockReset();
  fixtures.execution = undefined;
  fixtures.setMessages.mockReset();
  fixtures.messages = [
    {
      id: "saved",
      role: "assistant",
      content: "Previously saved history",
      created_at: "now",
    },
  ];
  fixtures.setMessages.mockImplementation((update) => {
    fixtures.messages =
      typeof update === "function" ? update(fixtures.messages) : update;
  });
});

it("automatically rebuilds one rejected policy change without duplicating the question", async () => {
  fixtures.stream.mockRejectedValueOnce(
    new ApiError({
      status: 409,
      detail: { code: "conversation_policy_changed" },
      userMessage: "Native conversation policy changed",
    }),
  );
  fixtures.stream.mockResolvedValueOnce(undefined);
  renderWithProviders(<ChatPage />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Send selected mode" }));
  await waitFor(() => expect(fixtures.stream).toHaveBeenCalledTimes(2));
  expect(fixtures.stream).toHaveBeenCalledTimes(2);
  expect(fixtures.messages.filter((m) => m.role === "user")).toHaveLength(1);
  const first = fixtures.stream.mock.calls[0];
  const rebuild = fixtures.stream.mock.calls[1];
  expect(first[15]).toBe(false);
  expect(rebuild[15]).toBe(true);
  expect(rebuild[0]).toBe("conversation");
  expect(rebuild[1]).toBe("Follow-up question");
  expect(rebuild[6]).toBe("sonnet");
  expect(rebuild[7]).toBe("agentic");
  expect(first[18]).toBe("high");
  expect(rebuild[18]).toBe("high");
  expect(
    fixtures.messages.some(
      (message) =>
        message.id === "saved" &&
        message.content === "Previously saved history",
    ),
  ).toBe(true);
});

it("keeps a selected document bound to its repository when browser storage is unavailable", async () => {
  vi.stubGlobal("localStorage", undefined);
  fixtures.stream.mockResolvedValueOnce(undefined);
  renderWithProviders(<ChatPage />, {
    initialEntries: [
      "/chat?scope_folder=selected-repository&scope_name=Selected&scope_file=README.md",
    ],
  });
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Send selected mode" }));
  expect(fixtures.stream.mock.calls[0][4]).toMatchObject({
    scopeFolderId: "selected-repository",
    scopeFilename: "README.md",
  });
});

it("shows progress before the first backend frame", async () => {
  fixtures.stream.mockImplementation(() => new Promise(() => {}));
  renderWithProviders(<ChatPage />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Send selected mode" }));
  expect(screen.getByText("Preparing your answer")).toBeInTheDocument();
});

it("reveals a large answer frame progressively while preserving its full content", async () => {
  const frames: FrameRequestCallback[] = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  fixtures.stream.mockImplementation(() => new Promise(() => {}));
  renderWithProviders(<ChatPage />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Send selected mode" }));
  const answer = "Evidence ".repeat(100);
  act(() => fixtures.stream.mock.calls[0][2](answer));
  expect(screen.getByTestId("streaming-answer")).toBeEmptyDOMElement();
  act(() => frames.shift()?.(16));
  const visible = screen.getByTestId("streaming-answer").textContent || "";
  expect(visible.length).toBeGreaterThan(0);
  expect(visible.length).toBeLessThan(30);
  expect(answer.startsWith(visible)).toBe(true);
});

it("does not loop when a rebuilt policy is rejected again", async () => {
  fixtures.stream.mockRejectedValue(
    new ApiError({
      status: 409,
      detail: { code: "conversation_policy_changed" },
      userMessage: "Policy changed",
    }),
  );
  renderWithProviders(<ChatPage />);
  await userEvent
    .setup()
    .click(screen.getByRole("button", { name: "Send selected mode" }));
  expect(
    await screen.findByRole("button", { name: "Rebuild context and retry" }),
  ).toBeInTheDocument();
  expect(fixtures.stream).toHaveBeenCalledTimes(2);
  expect(fixtures.messages.filter((m) => m.role === "user")).toHaveLength(1);
});

it.each([
  [undefined, "high"],
  ["medium", "medium"],
  ["low", "low"],
] as const)(
  "preserves recovered effort %s when rebuilding an accepted legacy Deep execution",
  async (effort, expected) => {
    fixtures.execution = {
      state: "failed",
      user_message_id: "question",
      scope_folder_id: null,
      scope_filename: null,
      turn_id: "turn",
      job_id: "job",
      conversation_id: "conversation",
      model: "sonnet",
      mode: "deep",
      reasoning_effort: effort,
    };
    fixtures.messages = [
      {
        id: "question",
        role: "user",
        content: "Original request",
        created_at: "now",
      },
    ];
    fixtures.stream.mockRejectedValueOnce(
      new ApiError({
        status: 409,
        detail: { code: "execution_uncertain" },
        userMessage: "Execution uncertain",
      }),
    );
    fixtures.stream.mockResolvedValueOnce(undefined);
    renderWithProviders(<ChatPage />);
    await userEvent
      .setup()
      .click(
        await screen.findByRole("button", {
          name: "Rebuild context and retry",
        }),
      );
    await waitFor(() => expect(fixtures.stream).toHaveBeenCalledTimes(2));
    expect(fixtures.stream.mock.calls[0][18]).toBe(expected);
    expect(fixtures.stream.mock.calls[1][18]).toBe(expected);
  },
);
