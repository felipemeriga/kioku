import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import SettingsPage from "./SettingsPage";

const api = vi.hoisted(() => ({
  fetchApiKeys: vi.fn(),
  fetchRootFolders: vi.fn(),
  fetchUsageByConversation: vi.fn(),
  fetchUsageByMonth: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));
vi.mock("../lib/api", () => ({ ...api, ApiError: class extends Error {} }));
vi.mock("../components/NotionIntegrationSection", () => ({
  NotionIntegrationSection: () => <div>Notion settings</div>,
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
  api.fetchApiKeys.mockResolvedValue([
    {
      id: "key-1",
      name: "Laptop",
      scope_folder_id: "root-1",
      scope_folder_name: "Personal",
      created_at: "2026-10-24T10:00:00Z",
    },
  ]);
  api.fetchRootFolders.mockResolvedValue([{ id: "root-1", name: "Personal" }]);
  api.fetchUsageByMonth.mockResolvedValue([
    { month: "2026-10", input_tokens: 100, output_tokens: 50, cost_usd: 2.5 },
    { month: "2026-09", input_tokens: 300, output_tokens: 50, cost_usd: 1.25 },
  ]);
  api.fetchUsageByConversation.mockResolvedValue([
    {
      conversation_id: "c-1",
      title: "First",
      input_tokens: 100,
      output_tokens: 50,
      cost_usd: 2.5,
    },
    {
      conversation_id: "c-2",
      title: "Second",
      input_tokens: 300,
      output_tokens: 50,
      cost_usd: 1.25,
    },
  ]);
  api.createApiKey.mockResolvedValue({ key: "test-secret-shown-once" });
  api.revokeApiKey.mockResolvedValue(undefined);
});

describe("Settings page", () => {
  it("computes summary totals and monthly bars from actual usage responses", async () => {
    renderWithProviders(<SettingsPage />, {
      initialEntries: ["/settings?tab=usage"],
    });
    const summary = screen.getByTestId("usage-summary");
    await within(summary).findByText("$3.75");
    expect(within(summary).getByText("500")).toBeInTheDocument();
    expect(within(summary).getByText("2")).toBeInTheDocument();
    expect(
      await screen.findByRole("img", { name: /October 2026: \$2.50/ })
    ).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("First");
    expect(screen.getByText("All recorded usage")).toBeInTheDocument();
  });

  it("keeps stored keys private, generates with the selected scope and confirms revocation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />);
    await screen.findByText("Laptop");
    expect(
      screen.getByText("Key kept private · Personal scope")
    ).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Key name"));
    await user.type(screen.getByLabelText("Key name"), "Workstation");
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Personal" }));
    await user.click(screen.getByRole("button", { name: "Generate API key" }));
    await waitFor(() =>
      expect(api.createApiKey).toHaveBeenCalledWith("Workstation", "root-1")
    );
    expect(await screen.findByLabelText("New API key")).toHaveValue(
      "test-secret-shown-once"
    );
    await user.click(screen.getByRole("button", { name: "Revoke key" }));
    expect(api.revokeApiKey).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /^Revoke$/,
      })
    );
    await waitFor(() => expect(api.revokeApiKey).toHaveBeenCalledWith("key-1"));
  });

  it("copies the displayed endpoint and scoped authentication configuration", async () => {
    const user = userEvent.setup();
    const writeText = vi
      .spyOn(navigator.clipboard, "writeText")
      .mockResolvedValue(undefined);
    vi.stubEnv("VITE_MCP_URL", "https://mcp.example.test/sse");
    renderWithProviders(<SettingsPage />, {
      initialEntries: ["/settings?tab=mcp-client"],
    });
    expect(screen.getByLabelText("Server URL")).toHaveValue(
      "https://mcp.example.test/sse"
    );
    await user.click(
      screen.getByRole("button", { name: "Copy configuration" })
    );
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('"url": "https://mcp.example.test/sse"')
    );
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining("Bearer YOUR_SCOPED_API_KEY")
    );
    expect(
      screen.getByText("https://mcp.example.test/mcp")
    ).toBeInTheDocument();
  });
});
