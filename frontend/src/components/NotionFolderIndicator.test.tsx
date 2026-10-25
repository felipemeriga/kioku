import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import * as api from "../lib/api";
import NotionFolderIndicator from "./NotionFolderIndicator";
const config = {
  id: "n1",
  root_folder_id: "direct",
  notion_page_id: "page",
  notion_page_title: "Project",
  fast_poll_interval_min: 5,
  last_fast_sync_at: "2026-10-24T10:00:00Z",
  last_full_sync_at: null,
  last_error: null,
};
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "fetchNotionConfigs").mockResolvedValue([config]);
  vi.spyOn(api, "fetchActiveIngestionJobs").mockResolvedValue([]);
});
describe("Direct Notion folder indicator", () => {
  it("marks only the configured target and shares the config read across tree/card/title instances", async () => {
    renderWithProviders(
      <>
        <NotionFolderIndicator folderId="parent" />
        <NotionFolderIndicator folderId="direct" />
        <NotionFolderIndicator folderId="direct" />
        <NotionFolderIndicator folderId="child" />
      </>
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("notion-folder-direct")).toHaveLength(2)
    );
    expect(
      screen.queryByTestId("notion-folder-parent")
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("notion-folder-child")).not.toBeInTheDocument();
    expect(api.fetchNotionConfigs).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole("link")[0]).toHaveAttribute(
      "href",
      "/settings?tab=integrations"
    );
    expect(screen.getAllByRole("link")[0]).toHaveAccessibleName(/Last synced/);
  });
  it("makes actual sync failures accessible without a banner", async () => {
    vi.mocked(api.fetchNotionConfigs).mockResolvedValue([
      { ...config, last_error: "Sanitized upstream unavailable" },
    ]);
    renderWithProviders(<NotionFolderIndicator folderId="direct" />);
    expect(
      await screen.findByRole("link", {
        name: /Sanitized upstream unavailable/,
      })
    ).toBeInTheDocument();
  });
});
