import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import ChatPage from "./ChatPage";
import { ApiError } from "../lib/api";

const fixtures = vi.hoisted(() => ({
  stream: vi.fn(),
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
  }) => (
    <>
      <span>{props.currentStage?.detail}</span>
      <button
        onClick={() =>
          props.onSend("Follow-up question", undefined, "sonnet", "deep", true)
        }
      >
        Send selected mode
      </button>
    </>
  ),
}));
vi.mock("../components/ScopePickerDialog", () => ({ default: () => null }));
vi.mock("../components/DocumentViewerDrawer", () => ({ default: () => null }));

afterEach(() => vi.unstubAllGlobals());

beforeEach(() => {
  fixtures.stream.mockReset();
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
  expect(rebuild[7]).toBe("deep");
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
