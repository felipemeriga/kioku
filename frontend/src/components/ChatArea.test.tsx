// frontend/src/components/ChatArea.test.tsx
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
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
      />
    );
    expect(screen.getByText("Searching documents...")).toBeInTheDocument();
  });

  it("renders messages when provided", () => {
    const messages = [
      { id: "1", role: "user" as const, content: "Hello", created_at: "" },
      { id: "2", role: "assistant" as const, content: "Hi there", created_at: "" },
    ];
    renderWithProviders(
      <ChatArea {...defaultProps} messages={messages} />
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("Hi there")).toBeInTheDocument();
  });
});
