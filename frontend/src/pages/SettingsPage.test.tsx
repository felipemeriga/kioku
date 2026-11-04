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
  fetchUsageAttribution: vi.fn(),
  fetchNativeActiveSessions: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));
vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: { email: "felipe.meriga@gmail.com" } }),
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
  api.fetchUsageAttribution.mockResolvedValue({
    month: "2026-11",
    total_cost_usd: "0.0069",
    unpriced_calls: 0,
    call_count: 2,
    by_source: { chat: "0.004", mihari: "0.0029" },
    by_repository: [{ folder_id: "f1", name: "Kioku", cost_usd: "0.0029" }],
    responses: [
      {
        response_id: "r1",
        title: "First",
        created_at: "2026-11-03T10:00:00Z",
        cost_usd: "0.004",
        rounds: [
          {
            round: 1,
            model: "claude-haiku-4-5-20251001",
            operation: "answer",
            cost_usd: "0.004",
            input_tokens: 100,
            output_tokens: 50,
            cache_write_tokens: 10,
            cache_read_tokens: 20,
          },
        ],
        additional_calls: [],
      },
    ],
    mihari_calls: [
      {
        created_at: "2026-11-03T10:01:00Z",
        operation: "documentation",
        repository: "Kioku",
        model: "claude-haiku-4-5-20251001",
        cost_usd: "0.0029",
      },
    ],
  });
  api.fetchNativeActiveSessions.mockResolvedValue({
    available: true,
    sessions: [],
    queued_counts: { total: 0 },
  });
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
      await screen.findByRole("img", { name: /October 2026: \$2.50/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("First");
    expect(screen.getByText("All recorded usage")).toBeInTheDocument();
    expect(
      await screen.findByText("Mihari · all watched repositories"),
    ).toBeInTheDocument();
    expect(screen.getByText("Chat responses and rounds")).toBeInTheDocument();
  });

  it("keeps stored keys private, generates with the selected scope and confirms revocation", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />);
    await screen.findByText("Laptop");
    expect(
      screen.getByText("Key kept private · Personal scope"),
    ).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Key name"));
    await user.type(screen.getByLabelText("Key name"), "Workstation");
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: "Personal" }));
    await user.click(screen.getByRole("button", { name: "Generate API key" }));
    await waitFor(() =>
      expect(api.createApiKey).toHaveBeenCalledWith("Workstation", "root-1"),
    );
    expect(await screen.findByLabelText("New API key")).toHaveValue(
      "test-secret-shown-once",
    );
    await user.click(screen.getByRole("button", { name: "Revoke key" }));
    expect(api.revokeApiKey).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /^Revoke$/,
      }),
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
      "https://mcp.example.test/sse",
    );
    await user.click(
      screen.getByRole("button", { name: "Copy configuration" }),
    );
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining('"url": "https://mcp.example.test/sse"'),
    );
    expect(writeText).toHaveBeenCalledWith(
      expect.stringContaining("Bearer YOUR_SCOPED_API_KEY"),
    );
    expect(
      screen.getByText("https://mcp.example.test/mcp"),
    ).toBeInTheDocument();
  });
});

it("shows current native sessions with owner, execution identity, scope and elapsed time", async () => {
  api.fetchNativeActiveSessions.mockResolvedValue({
    available: true,
    queued_counts: { total: 1 },
    sessions: [
      {
        job_id: "active-job",
        attempt_id: "active-attempt",
        native_session_id: "native-session",
        owner_id: "owner",
        owner_label: "owner@example.com",
        caller: "backend",
        conversation_id: "conversation",
        folder_ids: ["repo-folder"],
        operation: "rag_agent",
        profile: "chat",
        model_requested: "claude-haiku-4-5-20251001",
        native_cli_version: "2.1.318",
        state: "running",
        started_at: "2026-11-04T12:00:00Z",
        elapsed_seconds: 12,
      },
    ],
  });
  renderWithProviders(<SettingsPage />, {
    initialEntries: ["/settings?tab=usage"],
  });
  const panel = await screen.findByTestId("native-active-sessions");
  await within(panel).findByText(/owner@example.com.*running.*12s/);
  expect(
    within(panel).getByText(/active-job.*active-attempt.*native-session/),
  ).toBeInTheDocument();
  expect(
    within(panel).getByText(/conversation.*repo-folder/),
  ).toBeInTheDocument();
});
