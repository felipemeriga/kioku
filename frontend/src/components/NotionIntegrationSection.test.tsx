import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import { NotionIntegrationSection } from "./NotionIntegrationSection";

const api = vi.hoisted(() => ({
  fetchNotionConfigs: vi.fn(),
  fetchFolders: vi.fn(),
  fetchActiveIngestionJobs: vi.fn(),
  fetchNotionPending: vi.fn(),
  connectNotion: vi.fn(),
  disconnectNotion: vi.fn(),
  fetchIngestionJob: vi.fn(),
  listNotionPages: vi.fn(),
  reconcileNotionNow: vi.fn(),
  syncNotionNow: vi.fn(),
}));
vi.mock("../lib/api", () => ({ ...api, ApiError: class extends Error {} }));

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchNotionConfigs.mockResolvedValue([
    {
      id: "cfg-1",
      root_folder_id: "root-1",
      notion_page_id: "page-1",
      notion_page_title: "Workspace notes",
      fast_poll_interval_min: 5,
      last_fast_sync_at: "2026-10-24T10:00:00Z",
      last_full_sync_at: null,
      last_error: null,
    },
  ]);
  api.fetchFolders.mockResolvedValue([{ id: "root-1", name: "Personal" }]);
  api.fetchActiveIngestionJobs.mockResolvedValue([]);
  api.fetchNotionPending.mockResolvedValue({
    pending: [],
    total_in_notion: 12,
  });
});

describe("Notion settings", () => {
  it("shows actual connection metadata and reports completeness only after checking", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NotionIntegrationSection />);
    expect(
      await screen.findByRole("heading", { name: "Workspace notes" })
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Personal" })).toHaveAttribute(
      "href",
      "/documents?folder=root-1"
    );
    expect(
      screen.queryByText("All 12 Notion pages are synced.")
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Check for changes" }));
    expect(
      await screen.findByText("All 12 Notion pages are synced.")
    ).toBeInTheDocument();
    expect(api.fetchNotionPending).toHaveBeenCalledWith("cfg-1");
    expect(
      screen.getByRole("button", { name: "Sync now" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open folder integrations" })
    ).toHaveAttribute("href", "/documents");
  });

  it("does not present a fetch failure as an empty collection", async () => {
    api.fetchNotionConfigs.mockRejectedValue(new Error("Offline"));
    renderWithProviders(<NotionIntegrationSection />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load Notion configs"
    );
    expect(
      screen.queryByText(/No folders synced with Notion yet/)
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
