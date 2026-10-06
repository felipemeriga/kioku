import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import BriefingPanel from "./BriefingPanel";
import * as api from "../lib/api";
import type { BriefingResponse } from "../lib/api";

const staleBriefingFixture: BriefingResponse = {
  folder: { id: "f1", name: "my-repo", kind: "repo" },
  schema_version: 1,
  last_generated_at: "2026-01-01T00:00:00Z",
  sections: {
    overview: {
      content: "A test repo",
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    architecture: {
      content: "Monorepo",
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    preferences: {
      content: null,
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    important_files: {
      content: null,
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    how_it_runs: {
      content: null,
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    deployment: {
      content: null,
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    dependencies: {
      content: null,
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    activity: {
      content: null,
      status: "auto",
      provenance: "auto",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
  },
  freshness: {
    head_sha: "abc1234",
    commits_behind: 5,
    stale_sections: ["overview", "architecture"],
    changed_files: 3,
    checked_at: "2026-01-02T00:00:00Z",
  },
  index_status: {
    git_updates_at: "2026-01-01T12:00:00Z",
    head_sha: "abc1234",
    graph_at: "2026-01-01T11:00:00Z",
    graph_sha: "abc1234",
    graph_nodes: 100,
    graph_edges: 200,
    semantic_code_at: "2026-01-01T10:00:00Z",
  },
};

describe("BriefingPanel", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders the briefing title", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    // New design: overline is "BRIEFING" (all-caps hudLabel)
    await waitFor(() =>
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument()
    );
  });

  it("does not render the 'kioku init --force' warning", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    // Wait for load to complete
    await waitFor(() =>
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/kioku init --force/)).not.toBeInTheDocument();
  });

  it("does not render index status cards (Git updates / Graph / Semantic code)", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    await waitFor(() =>
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument()
    );
    expect(screen.queryByText("Git updates")).not.toBeInTheDocument();
  });

  it("collapses lower sections by default and expands on click", async () => {
    const fixture: BriefingResponse = {
      ...staleBriefingFixture,
      sections: {
        ...staleBriefingFixture.sections,
        preferences: {
          content: "Prefer uv over pip for Python packages.",
          status: "auto",
          provenance: "auto",
          updated_at: "2026-01-01T00:00:00Z",
          updated_by: null,
        },
      },
    };
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(fixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);

    // Wait for the panel to load
    await waitFor(() =>
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument()
    );

    // The preferences content should NOT be visible initially (collapsed)
    expect(
      screen.queryByText("Prefer uv over pip for Python packages.")
    ).not.toBeInTheDocument();

    // The collapsed row button for "Preferences" should be visible
    // (aria-expanded="false" distinguishes it from the SectionRail nav button)
    const allPrefsButtons = screen.getAllByRole("button", {
      name: /preferences/i,
    });
    const prefsRow = allPrefsButtons.find(
      (btn) => btn.getAttribute("aria-expanded") === "false"
    );
    expect(prefsRow).toBeDefined();

    // Click to expand
    fireEvent.click(prefsRow!);

    // Now the content should be visible
    await waitFor(() =>
      expect(
        screen.getByText("Prefer uv over pip for Python packages.")
      ).toBeInTheDocument()
    );
  });
});
