// frontend/src/components/ChatArea.test.tsx
import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import ChatArea from "./ChatArea";

const defaultProps = {
  messages: [],
  streamingContent: "",
  isStreaming: false,
  currentStage: null,
  onSend: vi.fn(),
};

describe("ChatArea", () => {
  it("keeps scope beside the composer without a redundant thread header", async () => {
    const pick = vi.fn();
    const user = userEvent.setup();
    const { container } = renderWithProviders(
      <ChatArea {...defaultProps} onPickScope={pick} />,
    );
    expect(container.querySelector(".chat-thread-header")).toBeNull();
    const scope = screen.getByRole("button", { name: "Scope" });
    expect(scope.closest(".chat-composer")).not.toBeNull();
    await user.click(scope);
    expect(pick).toHaveBeenCalledOnce();
  });

  it("renders empty state with suggestion chips when no messages", () => {
    renderWithProviders(<ChatArea {...defaultProps} />);
    expect(screen.getByText("Ask your second brain.")).toBeInTheDocument();
    expect(screen.getByText("Summarize my documents")).toBeInTheDocument();
    expect(screen.getByText("What topics are covered?")).toBeInTheDocument();
  });

  it("fires onSend when clicking a suggestion chip", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    renderWithProviders(<ChatArea {...defaultProps} onSend={onSend} />);
    await user.click(screen.getByText("Summarize my documents"));
    expect(onSend).toHaveBeenCalledWith("Summarize my documents");
  });

  it("renders ThinkingBar when currentStage is set", () => {
    renderWithProviders(
      <ChatArea
        {...defaultProps}
        isStreaming={true}
        currentStage={{ stage: "searching" }}
      />,
    );
    // ThinkingBar renders the StageTabs pipeline; 探索 = Searching.
    expect(screen.getByText("探索")).toBeInTheDocument();
    expect(screen.getByText(/Searching/)).toBeInTheDocument();
  });

  it("renders messages when provided", () => {
    const messages = [
      { id: "1", role: "user" as const, content: "Hello", created_at: "" },
      {
        id: "2",
        role: "assistant" as const,
        content: "Hi there",
        created_at: "",
      },
    ];
    renderWithProviders(<ChatArea {...defaultProps} messages={messages} />);
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Hi there")).toBeInTheDocument();
  });
});

it("scrolls a new send to its immediate progress even when reading older messages", () => {
  const scroll = vi
    .spyOn(Element.prototype, "scrollIntoView")
    .mockImplementation(() => {});
  const props = {
    messages: [],
    streamingContent: "",
    onSend: vi.fn(),
    currentStage: null,
  };
  const view = renderWithProviders(<ChatArea {...props} isStreaming={false} />);
  const thread = view.container.querySelector(".chat-workspace > div")!;
  Object.defineProperties(thread, {
    scrollHeight: { value: 1000 },
    clientHeight: { value: 100 },
    scrollTop: { value: 0 },
  });
  fireEvent.scroll(thread);
  scroll.mockClear();
  view.rerender(
    <ChatArea
      {...props}
      isStreaming
      currentStage={{ stage: "thinking", detail: "Preparing your answer" }}
    />,
  );
  expect(screen.getByTestId("thinking-bar")).toBeInTheDocument();
  expect(scroll).toHaveBeenCalledWith({ behavior: "instant", block: "end" });
});
