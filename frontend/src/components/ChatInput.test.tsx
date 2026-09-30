// frontend/src/components/ChatInput.test.tsx
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import ChatInput from "./ChatInput";

// Mock the api module
vi.mock("../lib/api", () => ({
  fetchDocumentFilters: vi.fn().mockResolvedValue({ topics: [], keywords: [] }),
  uploadDocument: vi.fn(),
  getAuthHeaders: vi.fn().mockResolvedValue({ Authorization: "Bearer test" }),
}));

describe("ChatInput", () => {
  it("renders the text input", () => {
    renderWithProviders(<ChatInput onSend={vi.fn()} disabled={false} />);
    expect(
      screen.getByPlaceholderText("Ask a question about your documents...")
    ).toBeInTheDocument();
  });

  it("disables input when disabled prop is true", () => {
    renderWithProviders(<ChatInput onSend={vi.fn()} disabled={true} />);
    const input = screen.getByPlaceholderText(
      "Ask a question about your documents..."
    );
    expect(input).toBeDisabled();
  });

  it("calls onSend when pressing Enter with text", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    renderWithProviders(<ChatInput onSend={onSend} disabled={false} />);
    const input = screen.getByPlaceholderText(
      "Ask a question about your documents..."
    );
    await user.type(input, "test message{Enter}");
    // defaults: Sonnet + Reasoning + Debug on
    expect(onSend).toHaveBeenCalledWith(
      "test message",
      undefined,
      "sonnet",
      true,
      true
    );
  });
});
