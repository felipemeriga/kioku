import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
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
      provenance: "auto_populator",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    architecture: {
      content: "Monorepo",
      status: "auto",
      provenance: "auto_populator",
      updated_at: "2026-01-01T00:00:00Z",
      updated_by: null,
    },
    preferences: {
      content: null,
      status: "auto",
      provenance: "auto_populator",
      updated_at: null,
      updated_by: null,
    },
    important_files: {
      content: null,
      status: "auto",
      provenance: "auto_populator",
      updated_at: null,
      updated_by: null,
    },
    how_it_runs: {
      content: null,
      status: "auto",
      provenance: "auto_populator",
      updated_at: null,
      updated_by: null,
    },
    deployment: {
      content: null,
      status: "auto",
      provenance: "auto_populator",
      updated_at: null,
      updated_by: null,
    },
    dependencies: {
      content: null,
      status: "auto",
      provenance: "auto_populator",
      updated_at: null,
      updated_by: null,
    },
    activity: {
      content: null,
      status: "auto",
      provenance: "auto_populator",
      updated_at: null,
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
    await waitFor(() =>
      expect(screen.getByText(/Briefing/)).toBeInTheDocument()
    );
  });

  it("does not render the 'kioku init --force' warning", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    // Wait for load to complete
    await waitFor(() =>
      expect(screen.getByText(/Briefing/)).toBeInTheDocument()
    );
    expect(screen.queryByText(/kioku init --force/)).not.toBeInTheDocument();
  });

  it("does not render index status cards (Git updates / Graph / Semantic code)", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    await waitFor(() =>
      expect(screen.getByText(/Briefing/)).toBeInTheDocument()
    );
    expect(screen.queryByText("Git updates")).not.toBeInTheDocument();
  });
});
