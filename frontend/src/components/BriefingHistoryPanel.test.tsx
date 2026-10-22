import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
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

  it("shows a per-section diff when two versions are selected", async () => {
    vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
    vi.spyOn(api, "fetchBriefingVersion").mockImplementation(async (_f, id) =>
      id === "v2" ? V("new") : V("old")
    );
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    await waitFor(() => screen.getByText("overview"));
    fireEvent.click(screen.getByTestId("version-v1"));
    fireEvent.click(screen.getByTestId("version-v2"));
    await waitFor(() =>
      expect(screen.getByTestId("diff-overview")).toBeInTheDocument()
    );
  });

  it("calls restore and invalidates", async () => {
    vi.spyOn(api, "fetchBriefingHistory").mockResolvedValue(META);
    const spy = vi
      .spyOn(api, "restoreBriefingVersion")
      .mockResolvedValue({ ok: true, restored_from: "v1" });
    renderWithProviders(<BriefingHistoryPanel folderId="f1" />);
    await waitFor(() => screen.getByTestId("version-v1"));
    fireEvent.click(screen.getByTestId("restore-v1"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("f1", "v1"));
  });
});
