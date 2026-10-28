import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent, act } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import StatusPanel from "./StatusPanel";
import { refreshState } from "../lib/refreshState";
import * as api from "../lib/api";

describe("StatusPanel", () => {
  it("keeps refresh controls before the metrics and shows the real failure at the top", async () => {
    vi.spyOn(api, "getFolderStatus").mockResolvedValue({
      index_refresh_started_at: new Date(Date.now() - 1000).toISOString(),
      index_refresh_finished_at: new Date().toISOString(),
      index_refresh_error: "SANITIZED_TEST_FAILURE: connection refused",
      architecture_by: "watcher",
      overview_by: "kioku-watcher",
    } as api.FolderStatus);
    renderWithProviders(<StatusPanel folderId="f1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "SANITIZED_TEST_FAILURE"
    );
    expect(screen.getByText("Briefing")).toBeInTheDocument();
    expect(screen.queryByText("by watcher")).toBeNull();
    const actions = screen.getByTestId("status-actions");
    expect(
      actions.compareDocumentPosition(screen.getByText("Git updates")) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(screen.getByText("Refresh code index")).toBeEnabled();
  });

  beforeEach(() => vi.restoreAllMocks());

  it.each([false, true])(
    "polls completion or times out even with identical data (%s)",
    async (timeout) => {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
      const started = new Date(
        Date.now() - (timeout ? 30 * 60000 - 2000 : 1000)
      ).toISOString();
      const initial = {
        index_refresh_started_at: started,
        graph_at: "2026-10-21T18:01:15Z",
      } as api.FolderStatus;
      const spy = vi.spyOn(api, "getFolderStatus").mockResolvedValue(initial);
      const view = renderWithProviders(<StatusPanel folderId="f1" />);
      await screen.findByText("Refreshing…");
      if (!timeout)
        spy.mockResolvedValue({
          ...initial,
          index_refresh_finished_at: new Date().toISOString(),
        });
      try {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(5000);
        });
        expect(
          screen.getByText(timeout ? /Refresh timed out/ : /Refresh completed/)
        ).toBeInTheDocument();
        expect(screen.queryByText("Refreshing…")).not.toBeInTheDocument();
      } finally {
        view.unmount();
        vi.useRealTimers();
      }
    }
  );

  it("uses job completion rather than content changes", () => {
    const started = "2026-10-23T03:05:56Z";
    const finished = "2026-10-23T03:06:02Z";
    const now = Date.parse(finished);
    expect(refreshState(started, null, null, now)).toBe("running");
    expect(refreshState(started, finished, null, now)).toBe("completed");
    expect(refreshState(started, finished, "failed", now)).toBe("failed");
    expect(refreshState(started, null, null, now + 31 * 60000)).toBe(
      "timed-out"
    );
    expect(refreshState(finished, started, null, now)).toBe("running");
  });

  it.each([null, "failed"])(
    "shows completed/no-op or failure after reload (%s)",
    async (error) => {
      vi.spyOn(api, "getFolderStatus").mockResolvedValue({
        graph_at: "2026-10-21T18:01:15Z",
        index_refresh_started_at: new Date(Date.now() - 7000).toISOString(),
        index_refresh_finished_at: new Date().toISOString(),
        index_refresh_error: error,
      } as api.FolderStatus);
      renderWithProviders(<StatusPanel folderId="f1" />);
      await screen.findByText(error ? /Refresh failed/ : /Refresh completed/);
      expect(screen.queryByText("Refreshing…")).not.toBeInTheDocument();
      expect(screen.getByText("Refresh code index")).toBeEnabled();
    }
  );

  it("groups the briefing status into one row", async () => {
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
      expect(screen.getByText("Briefing")).toBeInTheDocument()
    );
    expect(screen.queryByText("Architecture")).not.toBeInTheDocument();
    expect(screen.queryByText("Detailed docs")).not.toBeInTheDocument();
    expect(screen.getByText("Semantic code")).toBeInTheDocument();
  });

  it("shows a fresh briefing review without changing old content dates", async () => {
    vi.spyOn(api, "getFolderStatus").mockResolvedValue({
      architecture_at: "2026-09-01T00:00:00Z",
      overview_at: "2026-09-01T00:00:00Z",
      detailed_doc_at: "2026-09-01T00:00:00Z",
      briefing_reviewed_at: new Date().toISOString(),
      briefing_reviewed_sha: "a".repeat(40),
    } as api.FolderStatus);
    renderWithProviders(<StatusPanel folderId="f1" />);
    expect(await screen.findByText("Briefing")).toBeInTheDocument();
    expect(
      await screen.findByText(
        /Architecture, overview, and detailed docs reviewed at aaaaaaa/
      )
    ).toHaveTextContent("Content changed");
    expect(screen.getByText(/Reviewed/)).toBeInTheDocument();
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
    await waitFor(() =>
      expect(screen.getByText("Review briefing")).toBeEnabled()
    );
    fireEvent.click(screen.getByText("Review briefing"));
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
