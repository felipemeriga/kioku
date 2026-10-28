import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent, within } from "@testing-library/react";
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

  it("renders Markdown headings and commands in briefing sections", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue({
      ...staleBriefingFixture,
      sections: {
        ...staleBriefingFixture.sections,
        how_it_runs: {
          ...staleBriefingFixture.sections.how_it_runs,
          content: {
            requirements: ["Node.js is required for the web client."],
            local_dev: "### Run locally\n\nUse `npm run dev`.",
          },
        },
      },
    });
    renderWithProviders(<BriefingPanel folderId="f1" />);
    await screen.findByText(/BRIEFING/i);
    fireEvent.click(screen.getAllByText("How it runs").at(-1)!);
    expect(
      await screen.findByRole("heading", { name: "Run locally" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/### Run locally/)).not.toBeInTheDocument();
    expect(screen.getByText("Before you start")).toBeInTheDocument();
    expect(
      screen.getByText("Node.js is required for the web client."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Run and verify")).not.toBeInTheDocument();
  });

  it("collapses repeated requirements when the guide already has setup", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue({
      ...staleBriefingFixture,
      sections: {
        ...staleBriefingFixture.sections,
        how_it_runs: {
          ...staleBriefingFixture.sections.how_it_runs,
          content: {
            requirements: ["Rust toolchain"],
            local_dev: "### Prerequisites and setup\n\nInstall Rust.",
          },
        },
      },
    });
    renderWithProviders(<BriefingPanel folderId="f1" />);
    await screen.findByText(/Repository briefing/i);
    fireEvent.click(screen.getAllByText("How it runs").at(-1)!);
    expect(
      screen.getByText("Requirements at a glance (1)"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Before you start")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Prerequisites and setup" }),
    ).toBeInTheDocument();
  });

  it("shows deployment and activity as readable sections without duplicate field labels", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue({
      ...staleBriefingFixture,
      sections: {
        ...staleBriefingFixture.sections,
        deployment: {
          ...staleBriefingFixture.sections.deployment,
          content: {
            environments: ["Production on Dokploy"],
            how_to_deploy: "Run `release.yml` after CI passes.",
            ci_cd_notes: "CI runs tests before release.",
          },
        },
        activity: {
          ...staleBriefingFixture.sections.activity,
          content: { summary: "Recent work", highlights: ["Fixed indexing"] },
        },
      },
    });
    renderWithProviders(<BriefingPanel folderId="f1" />);
    await screen.findByText(/Repository briefing/i);
    fireEvent.click(screen.getAllByText("Deployment").at(-1)!);
    expect(
      screen.getByRole("heading", { name: "Release steps" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Release steps")).toHaveLength(1);
    expect(screen.getByText("Production on Dokploy")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Activity").at(-1)!);
    expect(
      screen.getByRole("heading", { name: "Recent highlights" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fixed indexing")).toBeInTheDocument();
  });

  it("adds the detailed document to the section navigation when one exists", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    vi.spyOn(api, "fetchDocumentation").mockResolvedValue({
      documentation: {
        content: "# Guide",
        abstract: "Guide summary",
        generated_at: "2026-01-01T00:00:00Z",
      },
    } as Awaited<ReturnType<typeof api.fetchDocumentation>>);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    const rail = await screen.findByRole("complementary", {
      name: "Briefing sections",
    });
    expect(
      await within(rail).findByRole("button", {
        name: /Detailed documentation/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders the briefing title", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    // New design: overline is "BRIEFING" (all-caps hudLabel)
    await waitFor(() =>
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument(),
    );
  });

  it("does not render the 'kioku init --force' warning", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    // Wait for load to complete
    await waitFor(() =>
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/kioku init --force/)).not.toBeInTheDocument();
  });

  it("does not render index status cards (Git updates / Graph / Semantic code)", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue(staleBriefingFixture);
    renderWithProviders(<BriefingPanel folderId="f1" />);
    await waitFor(() =>
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Git updates")).not.toBeInTheDocument();
  });

  it("collapses lower sections by default and expands on click", async () => {
    const fixture: BriefingResponse = {
      ...staleBriefingFixture,
      sections: {
        ...staleBriefingFixture.sections,
        how_it_runs: {
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
      expect(screen.getByText(/BRIEFING/i)).toBeInTheDocument(),
    );

    // The operating guide should NOT be visible initially (collapsed)
    expect(
      screen.queryByText("Prefer uv over pip for Python packages."),
    ).not.toBeInTheDocument();

    // The collapsed row button for "How it runs" should be visible
    // (aria-expanded="false" distinguishes it from the SectionRail nav button)
    const allPrefsButtons = screen.getAllByRole("button", {
      name: /how it runs/i,
    });
    const prefsRow = allPrefsButtons.find(
      (btn) => btn.getAttribute("aria-expanded") === "false",
    );
    expect(prefsRow).toBeDefined();

    // Click to expand
    fireEvent.click(prefsRow!);

    // Now the content should be visible
    await waitFor(() =>
      expect(
        screen.getByText("Prefer uv over pip for Python packages."),
      ).toBeInTheDocument(),
    );
  });

  it("keeps legacy preferences out of the briefing navigation", async () => {
    vi.spyOn(api, "fetchBriefing").mockResolvedValue({
      ...staleBriefingFixture,
      sections: {
        ...staleBriefingFixture.sections,
        preferences: {
          content: ["Legacy preference"],
          status: "auto",
          provenance: "auto",
          updated_at: "2026-01-01T00:00:00Z",
          updated_by: null,
        },
      } as BriefingResponse["sections"],
    });
    renderWithProviders(<BriefingPanel folderId="f1" />);
    await screen.findByText(/Repository briefing/i);
    expect(screen.queryByText("Preferences")).not.toBeInTheDocument();
    expect(screen.queryByText("Legacy preference")).not.toBeInTheDocument();
  });
});
