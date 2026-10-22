import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent, within } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { renderWithProviders } from "../test/renderWithProviders";
import BriefingHistoryPanel from "./BriefingHistoryPanel";
import * as api from "../lib/api";

const META = [
  {
    id: "v2",
    generated_at: "2026-10-22T02:00:00Z",
    trigger: "edit",
    updated_by: "u1",
    content_hash: "h2",
    changed_sections: ["overview"],
  },
  {
    id: "v1",
    generated_at: "2026-10-22T01:00:00Z",
    trigger: "seed",
    updated_by: null,
    content_hash: "h1",
    changed_sections: [],
  },
];

const V = (p: string) => ({
  id: "x",
  generated_at: "t",
  trigger: "edit",
  updated_by: "u1",
  sections: {
    overview: {
      status: "auto",
      content: { purpose: p, description: "" },
      provenance: "auto",
      updated_at: "t",
      updated_by: null,
    },
  },
});

describe("BriefingHistoryPanel", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("lists versions newest-first with changed-section chips", async () => {
    vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    await waitFor(() =>
      expect(screen.getByText("overview")).toBeInTheDocument()
    );
    expect(screen.getByText(/seed/i)).toBeInTheDocument();
  });

  it.each([
    ["v1", "v2"],
    ["v2", "v1"],
  ])(
    "shows chronological additions/removals for selection %s then %s",
    async (first, second) => {
      vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
      vi.spyOn(api, "fetchBriefingVersion").mockImplementation(async (_f, id) =>
        id === "v2" ? V("new") : V("old")
      );
      renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
      await waitFor(() => screen.getByText("overview"));
      fireEvent.click(screen.getByTestId(`version-${first}`));
      fireEvent.click(screen.getByTestId(`version-${second}`));
      await waitFor(() =>
        expect(screen.getByTestId("diff-overview")).toBeInTheDocument()
      );
      const diff = within(screen.getByTestId("diff-overview"));
      expect(diff.getByText("+ purpose: new")).toBeInTheDocument();
      expect(diff.getByText("- purpose: old")).toBeInTheDocument();
    }
  );

  it("calls restore and invalidates", async () => {
    vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
    const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    const spy = vi
      .spyOn(api, "restoreBriefingVersion")
      .mockResolvedValue({ ok: true, restored_from: "v1" });
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    await waitFor(() => screen.getByTestId("version-v1"));
    fireEvent.click(screen.getByTestId("restore-v1"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("f1", "v1"));
    await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Briefing restored.")).toBeInTheDocument();
  });

  it("shows a selected version without requiring a comparison", async () => {
    vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
    vi.spyOn(api, "fetchBriefingVersion").mockResolvedValue(
      V("historical content")
    );
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    fireEvent.click(await screen.findByTestId("version-v1"));
    expect(await screen.findByTestId("version-details")).toHaveTextContent(
      "historical content"
    );
  });

  it("reports a restore failure and re-enables the button", async () => {
    vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
    vi.spyOn(api, "restoreBriefingVersion").mockRejectedValue(
      new Error("Restore failed")
    );
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    fireEvent.click(await screen.findByTestId("restore-v1"));
    expect(await screen.findByText("Restore failed")).toBeInTheDocument();
    expect(screen.getByTestId("restore-v1")).toBeEnabled();
  });

  it("retries a failed version fetch", async () => {
    vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
    vi.spyOn(api, "fetchBriefingVersion")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(V("recovered"));
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    fireEvent.click(await screen.findByTestId("version-v1"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load this version."
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("version-details")).toHaveTextContent(
      "recovered"
    );
  });

  it("retries a failed history request", async () => {
    vi.spyOn(api, "fetchBriefingHistory")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(META);
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    expect(await screen.findByTestId("history-error")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByTestId("version-v1")).toBeInTheDocument();
  });

  it("loads older versions beyond the first page", async () => {
    const page = Array.from({ length: 50 }, (_, i) => ({
      ...META[0],
      id: `page-${i}`,
    }));
    const history = vi
      .spyOn(api, "fetchBriefingHistory")
      .mockResolvedValueOnce(page)
      .mockResolvedValueOnce(META);
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Load older versions" })
    );
    expect(await screen.findByTestId("version-v1")).toBeInTheDocument();
    expect(history).toHaveBeenLastCalledWith("f1", 50, 50);
  });
});
