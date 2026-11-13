import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import { apiFetch } from "../lib/api";
import ReportsPanel from "./ReportsPanel";
vi.mock("../lib/api", () => ({ apiFetch: vi.fn() }));
const weekly = {
  id: "11111111-1111-4111-8111-111111111111",
  kind: "weekly",
  period_start: "2026-11-09",
  period_end: "2026-11-15",
  timezone: "UTC",
  cutoff: "2026-11-13T10:00:00Z",
  status: "draft",
  revision: 2,
  generated_at: "2026-11-13T10:10:00Z",
  coverage: {
    github: "unavailable",
    journal_entries: 5,
    journal_entries_included: 5,
    original_events_included: 2,
    original_events: 20,
  },
  content: {
    title: "Player memory investigation",
    summary: "A budget was proposed; deployment remains unverified.",
    summary_source_ids: ["j1"],
    sections: [
      {
        heading: "Still open",
        items: [
          {
            text: "Measure actual RSS after the configuration change.",
            source_ids: ["j1", "o1"],
            evidence_quote: "deployment remains unverified",
          },
        ],
      },
    ],
  },
  sources: [
    {
      id: "j1",
      kind: "journal",
      date: "2026-11-13",
      journal_date: "2026-11-14",
      entry_id: "entry-1",
      text: "A budget was proposed; deployment remains unverified.",
    },
    {
      id: "o1",
      kind: "original",
      date: "2026-11-13",
      session_id: "22222222-2222-4222-8222-222222222222",
      event_id: "evt",
      text: "Runtime RSS: 8 GiB",
    },
  ],
};
const response = (value: unknown) => new Response(JSON.stringify(value));
function mount() {
  const onOpenHistory = vi.fn(),
    onOpenEvidence = vi.fn();
  renderWithProviders(
    <ReportsPanel
      folderId="repo"
      onOpenHistory={onOpenHistory}
      onOpenEvidence={onOpenEvidence}
    />
  );
  return { onOpenHistory, onOpenEvidence };
}
describe("ReportsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState({}, "", "/");
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      const url = String(path);
      if (url.includes("/reports?"))
        return response({
          reports: url.includes("monthly") ? [] : [weekly],
          timezone: "UTC",
          has_more: false,
        });
      return response({
        report: url.includes("revision=1")
          ? {
              ...weekly,
              revision: 1,
              content: { ...weekly.content, title: "Earlier proposal" },
            }
          : weekly,
        revisions: [{ revision: 2 }, { revision: 1 }],
      });
    });
  });
  it("shows the cutoff, scoped sources, and opens originals and the exact journal day", async () => {
    const callbacks = mount();
    expect(
      await screen.findByRole("heading", {
        name: "Player memory investigation",
      })
    ).toBeInTheDocument();
    expect(screen.getByText(/Sources through/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View evidence" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open original" })
    );
    expect(callbacks.onOpenEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        eventId: "evt",
        folderId: "repo",
        sessionId: weekly.sources[1].session_id,
      })
    );
    fireEvent.click(screen.getByRole("button", { name: "Summary sources" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Open in History" })
    );
    expect(callbacks.onOpenHistory).toHaveBeenCalledWith(
      "2026-11-14",
      "entry-1"
    );
  });
  it("switches to monthly without leaking the selected weekly content", async () => {
    mount();
    await screen.findByText("Player memory investigation");
    fireEvent.click(screen.getByRole("button", { name: "Monthly" }));
    expect(
      await screen.findByText("No monthly reports yet")
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Player memory investigation")
    ).not.toBeInTheDocument();
  });
  it("can read a previous immutable revision", async () => {
    mount();
    await screen.findByText("Player memory investigation");
    fireEvent.mouseDown(screen.getByRole("combobox", { name: "Revision" }));
    fireEvent.click(await screen.findByRole("option", { name: "Revision 1" }));
    expect(await screen.findByText("Earlier proposal")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith(
      expect.stringContaining("?revision=1")
    );
  });
  it("renders a styled retry state when the reports service is unavailable", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("offline"));
    mount();
    await waitFor(
      () =>
        expect(screen.getByRole("alert")).toHaveTextContent(
          "Could not load reports"
        ),
      { timeout: 5000 }
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
  it("ignores malformed report and revision parameters", async () => {
    window.history.replaceState(
      {},
      "",
      "/?report=bad<script>&report_revision=-2&report_kind=evil"
    );
    mount();
    await screen.findByText("Player memory investigation");
    expect(apiFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("<script>")
    );
    expect(apiFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("revision=-2")
    );
  });
});
