// frontend/src/components/ChatInput.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchChatModels } from "../lib/api";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import ChatInput from "./ChatInput";

// Mock the api module
vi.mock("../lib/api", () => ({
  uploadDocument: vi.fn(),
  getAuthHeaders: vi.fn().mockResolvedValue({ Authorization: "Bearer test" }),
  fetchChatModels: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(fetchChatModels).mockResolvedValue({ engine: "api", models: [] });
});

it("offers actual subscription models, deduplicates aliases, and disables paid choices", async () => {
  vi.mocked(fetchChatModels).mockResolvedValue({
    engine: "tsukai",
    models: [
      {
        value: "default",
        resolvedModel: "sonnet-current",
        displayName: "Default Sonnet",
        selectable: true,
        requires_usage_credits: false,
      },
      {
        value: "sonnet",
        resolvedModel: "sonnet-current",
        displayName: "Sonnet Current",
        selectable: true,
        requires_usage_credits: false,
      },
      {
        value: "haiku",
        resolvedModel: "haiku-current",
        displayName: "Haiku Current",
        selectable: true,
        requires_usage_credits: false,
      },
      {
        value: "opus",
        resolvedModel: "opus-current",
        displayName: "Opus Current",
        selectable: true,
        requires_usage_credits: false,
      },
      {
        value: "fable",
        resolvedModel: "fable-current",
        displayName: "Fable Current",
        selectable: false,
        requires_usage_credits: true,
      },
    ],
  });
  const user = userEvent.setup();
  const onSend = vi.fn();
  renderWithProviders(<ChatInput onSend={onSend} disabled={false} />);
  await user.click(await screen.findByText("Haiku Current"));
  expect(screen.queryByText("Default Sonnet")).not.toBeInTheDocument();
  expect(
    screen.getByRole("menuitem", {
      name: /Fable Current.*Extra usage credits/,
    }),
  ).toHaveAttribute("aria-disabled", "true");
  await user.click(screen.getByRole("menuitem", { name: "Opus Current" }));
  await user.type(
    screen.getByPlaceholderText("Ask a question about your documents..."),
    "question{Enter}",
  );
  expect(onSend).toHaveBeenCalledWith(
    "question",
    undefined,
    "opus-current",
    "agentic",
    true,
    "low",
  );
});

it("labels catalog failure instead of claiming legacy choices are discovered", async () => {
  vi.mocked(fetchChatModels).mockRejectedValue(new Error("unavailable"));
  const user = userEvent.setup();
  renderWithProviders(<ChatInput onSend={vi.fn()} disabled={false} />);
  await user.click(screen.getByText("Haiku"));
  expect(
    await screen.findByText("Model catalog unavailable — legacy choices shown"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("menuitem", { name: "Refresh model catalog" }),
  ).toBeInTheDocument();
});

it("restores a catalog model ID from a saved execution without replacing it with Haiku", async () => {
  vi.mocked(fetchChatModels).mockResolvedValue({
    engine: "tsukai",
    models: [
      {
        value: "opus",
        resolvedModel: "opus-current",
        displayName: "Opus Current",
        selectable: true,
        requires_usage_credits: false,
      },
    ],
  });
  const onSend = vi.fn();
  const user = userEvent.setup();
  renderWithProviders(
    <ChatInput
      conversationId="saved"
      onSend={onSend}
      disabled={false}
      restoredSettings={{ model: "opus-current", mode: "plain" }}
    />,
  );
  await screen.findByText("Opus Current");
  await user.type(
    screen.getByPlaceholderText("Ask a question about your documents..."),
    "follow up{Enter}",
  );
  expect(onSend).toHaveBeenCalledWith(
    "follow up",
    undefined,
    "opus-current",
    "plain",
    true,
    "low",
  );
});

it("does not offer cached native choices as fresh after a catalog refresh fails", async () => {
  vi.mocked(fetchChatModels)
    .mockResolvedValueOnce({
      engine: "tsukai",
      stale: true,
      models: [
        {
          value: "opus",
          resolvedModel: "opus-current",
          displayName: "Cached Opus",
          selectable: true,
          requires_usage_credits: false,
        },
      ],
    })
    .mockRejectedValue(new Error("unavailable"));
  const user = userEvent.setup();
  renderWithProviders(
    <ChatInput
      onSend={vi.fn()}
      disabled={false}
      restoredSettings={{ model: "opus-current", mode: "deep" }}
    />,
  );
  await user.click(await screen.findByText("Cached Opus"));
  await user.click(
    screen.getByRole("menuitem", { name: "Refresh model catalog" }),
  );
  expect(
    await screen.findByText("Model catalog unavailable — legacy choices shown"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("menuitem", { name: "Sonnet — stronger reasoning" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("menuitem", { name: "Cached Opus" }),
  ).not.toBeInTheDocument();
});

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
    // defaults: Haiku + Agentic + Low effort + Debug on
    expect(onSend).toHaveBeenCalledWith(
      "test message",
      undefined,
      "haiku",
      "agentic",
      true,
      "low",
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
  const view = renderWithProviders(
    <ChatInput
      conversationId="recovered"
      onSend={onSend}
      disabled={false}
      restoredSettings={{ model: "sonnet", mode: "plain" }}
    />,
  );
  view.rerender(
    <ChatInput conversationId="recovered" onSend={onSend} disabled={false} />,
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
    "low",
  );
});

it("sends independently selected effort and resets it for another conversation", async () => {
  const user = userEvent.setup();
  const onSend = vi.fn();
  const view = renderWithProviders(
    <ChatInput conversationId="first" onSend={onSend} disabled={false} />,
  );
  await user.click(
    screen.getByRole("button", { name: "Reasoning effort: low" }),
  );
  await user.click(
    screen.getByRole("menuitem", { name: "High — more reasoning" }),
  );
  await user.type(
    screen.getByPlaceholderText("Ask a question about your documents..."),
    "recall{Enter}",
  );
  expect(onSend).toHaveBeenCalledWith(
    "recall",
    undefined,
    "haiku",
    "agentic",
    true,
    "high",
  );
  view.rerender(
    <ChatInput conversationId="second" onSend={onSend} disabled={false} />,
  );
  expect(
    screen.getByRole("button", { name: "Reasoning effort: low" }),
  ).toBeInTheDocument();
});

it("restores medium effort and disables the selector during execution", async () => {
  renderWithProviders(
    <ChatInput
      onSend={vi.fn()}
      disabled={true}
      restoredSettings={{
        model: "haiku",
        mode: "agentic",
        reasoning_effort: "medium",
      }}
    />,
  );
  expect(
    screen.getByRole("button", { name: "Reasoning effort: medium" }),
  ).toHaveAttribute("aria-disabled", "true");
});
