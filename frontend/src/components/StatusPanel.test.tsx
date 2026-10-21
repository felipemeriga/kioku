import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import StatusPanel from "./StatusPanel";
import * as api from "../lib/api";

describe("StatusPanel", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders the six status cards", async () => {
    vi.spyOn(api, "getFolderStatus").mockResolvedValue({
      git_updates_at: null,
      head_sha: null,
      graph_at: null,
      graph_sha: null,
      graph_nodes: null,
      graph_edges: null,
      semantic_code_at: null,
      architecture_at: null,
      architecture_by: null,
      overview_at: null,
      overview_by: null,
      detailed_doc_at: null,
      index_refresh_started_at: null,
      sections_refresh_started_at: null,
    });
    renderWithProviders(<StatusPanel folderId="f1" />);
    await waitFor(() =>
      expect(screen.getByText("Architecture")).toBeInTheDocument()
    );
    expect(screen.getByText("Detailed docs")).toBeInTheDocument();
    expect(screen.getByText("Semantic code")).toBeInTheDocument();
  });

  it("calls refreshFolder with 'sections' when the detail button is clicked", async () => {
    vi.spyOn(api, "getFolderStatus").mockResolvedValue({
      git_updates_at: null,
      head_sha: null,
      graph_at: null,
      graph_sha: null,
      graph_nodes: null,
      graph_edges: null,
      semantic_code_at: null,
      architecture_at: null,
      architecture_by: null,
      overview_at: null,
      overview_by: null,
      detailed_doc_at: null,
      index_refresh_started_at: null,
      sections_refresh_started_at: null,
    });
    const spy = vi
      .spyOn(api, "refreshFolder")
      .mockResolvedValue({ started: true });
    renderWithProviders(<StatusPanel folderId="f1" />);
    await waitFor(() => screen.getByText("Refresh detail sections"));
    fireEvent.click(screen.getByText("Refresh detail sections"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("f1", "sections"));
  });

  it("shows a loading spinner until the status arrives", async () => {
    // Never resolves → the query stays pending.
    vi.spyOn(api, "getFolderStatus").mockReturnValue(
      new Promise<never>(() => {})
    );
    renderWithProviders(<StatusPanel folderId="f1" />);
    await waitFor(() =>
      expect(screen.getAllByRole("progressbar").length).toBeGreaterThan(0)
    );
    // Must not flash the misleading "never" fallback while loading.
    expect(screen.queryByText("never")).not.toBeInTheDocument();
  });

  it("shows an error with a Retry when the status fails to load", async () => {
    const spy = vi
      .spyOn(api, "getFolderStatus")
      .mockRejectedValue(new Error("boom"));
    renderWithProviders(<StatusPanel folderId="f1" />);
    await screen.findByText("Couldn't load status.");
    expect(spy).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("Retry"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });
});
