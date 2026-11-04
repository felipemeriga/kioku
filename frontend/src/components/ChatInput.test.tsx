// frontend/src/components/ChatInput.test.tsx
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import ChatInput from "./ChatInput";

// Mock the api module
vi.mock("../lib/api", () => ({
  uploadDocument: vi.fn(),
  getAuthHeaders: vi.fn().mockResolvedValue({ Authorization: "Bearer test" }),
}));

describe("ChatInput", () => {
  it("renders the text input", () => {
    renderWithProviders(<ChatInput onSend={vi.fn()} disabled={false} />);
    expect(
      screen.getByPlaceholderText("Ask a question about your documents..."),
    ).toBeInTheDocument();
  });

  it("disables input when disabled prop is true", () => {
    renderWithProviders(<ChatInput onSend={vi.fn()} disabled={true} />);
    const input = screen.getByPlaceholderText(
      "Ask a question about your documents...",
    );
    expect(input).toBeDisabled();
  });

  it("calls onSend when pressing Enter with text", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    renderWithProviders(<ChatInput onSend={onSend} disabled={false} />);
    const input = screen.getByPlaceholderText(
      "Ask a question about your documents...",
    );
    await user.type(input, "test message{Enter}");
    // defaults: Haiku + Deep + Debug on
    expect(onSend).toHaveBeenCalledWith(
      "test message",
      undefined,
      "haiku",
      "deep",
      true,
    );
  });

  it("starts another conversation on Haiku after selecting Sonnet", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    const view = renderWithProviders(
      <ChatInput conversationId="first" onSend={onSend} disabled={false} />,
    );
    await user.click(screen.getByText("Haiku"));
    await user.click(screen.getByText("Sonnet — stronger reasoning"));
    expect(screen.getByText("Sonnet")).toBeInTheDocument();
    view.rerender(
      <ChatInput conversationId="second" onSend={onSend} disabled={false} />,
    );
    expect(screen.getByText("Haiku")).toBeInTheDocument();
  });
});

it("restores accepted execution model and mode for the next follow-up", async () => {
  const onSend = vi.fn();
  renderWithProviders(
    <ChatInput
      conversationId="recovered"
      onSend={onSend}
      disabled={false}
      restoredSettings={{ model: "sonnet", mode: "plain" }}
    />,
  );
  const user = userEvent.setup();
  await user.type(
    screen.getByPlaceholderText("Ask a question about your documents..."),
    "follow up{Enter}",
  );
  expect(onSend).toHaveBeenCalledWith(
    "follow up",
    undefined,
    "sonnet",
    "plain",
    true,
  );
});
