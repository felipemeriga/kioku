import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
          {
            text: "Confirm the deployed budget against the runtime result.",
            source_ids: ["o1"],
            evidence_quote: "Runtime RSS: 8 GiB",
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
    sessionStorage.clear();
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
    expect(
      screen.getAllByRole("button", { name: /^Sources for / })
    ).toHaveLength(1);
    expect(screen.getByText("Sources (2)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Sources for / }));
    expect(
      screen.queryByRole("button", { name: "View evidence" })
    ).not.toBeInTheDocument();
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
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    );
    fireEvent.click(screen.getByText("Overview"));
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
    fireEvent.change(screen.getByRole("combobox", { name: "Revision" }), {
      target: { value: "1" },
    });
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
  it("restores the period after leaving and returning to Reports", async () => {
    const props = {
      folderId: "repo",
      onOpenHistory: vi.fn(),
      onOpenEvidence: vi.fn(),
    };
    const first = renderWithProviders(<ReportsPanel {...props} />);
    await screen.findByText("Player memory investigation");
    fireEvent.click(screen.getByRole("button", { name: "Monthly" }));
    await screen.findByText("No monthly reports yet");
    first.unmount();
    renderWithProviders(<ReportsPanel {...props} />);
    expect(
      await screen.findByText("No monthly reports yet")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Monthly" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });
});

const timeline = {
  ...weekly,
  timezone: "America/Sao_Paulo",
  content: {
    format_version: 2,
    title: "NBA reliability and telemetry",
    summary:
      "The investigation moved from stream failures to consumer-group isolation. Its effect remains unconfirmed.",
    summary_source_ids: ["j1", "o1"],
    outcomes: [
      {
        text: "The consumer-group change reached main.",
        source_ids: ["c1"],
        evidence_quote: "Merged consumer-group isolation",
      },
    ],
    merges: [
      {
        at: "2026-11-13T17:12:00Z",
        date: "2026-11-13",
        pr_number: 485,
        sha: "a".repeat(40),
        title: "Live consumer-group isolation",
        source_ids: ["c1"],
        evidence_quote: "Merged consumer-group isolation",
      },
      {
        at: "2026-11-13T16:55:00Z",
        date: "2026-11-13",
        pr_number: 484,
        sha: "b".repeat(40),
        title: "Puck-gap telemetry",
        source_ids: ["c2"],
        evidence_quote: "Merged puck-gap telemetry",
      },
    ],
    topics: [
      {
        id: "nba-sse",
        title: "NBA SSE reliability",
        subtitle:
          "A consumer-group hypothesis followed the failure investigation",
        updates: [
          {
            date: "2026-11-12",
            title: "Correlated the SSE failures",
            text: "Gateway request IDs and NAT observations informed the investigation.",
            detail: "The failure signature did not establish causality.",
            source_ids: ["j1"],
            evidence_quote: "A budget was proposed",
          },
          {
            date: "2026-11-13",
            title: "Isolated live consumer groups",
            text: "PR #485 was merged to test whether shared groups contributed to the SSE failures.",
            detail: "Staging deployment was queued at 14:27.",
            source_ids: ["j1", "c1", "o1"],
            evidence_quote: "Merged consumer-group isolation",
          },
        ],
        final_state: {
          status: "Changes merged",
          items: [
            {
              text: "CGID isolation reached main; its effect on the failure pattern remains unconfirmed.",
              source_ids: ["c1", "o1"],
              evidence_quote: "Merged consumer-group isolation",
            },
          ],
        },
      },
      {
        id: "nhl",
        title: "NHL telemetry",
        subtitle: "Archive comparisons informed the change",
        updates: [
          {
            date: "2026-11-13",
            title: "Telemetry reached main",
            text: "PR #484 merged after archive comparisons.",
            detail: "",
            source_ids: ["c2"],
            evidence_quote: "Merged puck-gap telemetry",
          },
        ],
        final_state: {
          status: "Merged",
          items: [
            {
              text: "The telemetry implementation reached main.",
              source_ids: ["c2"],
              evidence_quote: "Merged puck-gap telemetry",
            },
          ],
        },
      },
    ],
  },
  sources: [
    ...weekly.sources,
    {
      id: "c1",
      kind: "git_commit",
      date: "2026-11-13",
      observed_at: "2026-11-13T17:12:00Z",
      text: "Merged consumer-group isolation",
      url: `https://github.com/cosm-eng/c360-lead/commit/${"a".repeat(40)}`,
    },
    {
      id: "c2",
      kind: "git_commit",
      date: "2026-11-13",
      text: "Merged puck-gap telemetry",
      url: `https://github.com/cosm-eng/c360-lead/commit/${"b".repeat(40)}`,
    },
  ],
};
function mockTimeline() {
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    const url = String(path);
    const monthly = {
      ...timeline,
      id: "33333333-3333-4333-8333-333333333333",
      kind: "monthly",
      period_start: "2026-11-01",
      period_end: "2026-11-30",
      content: { ...timeline.content, title: "November reliability work" },
    };
    if (url.includes("/reports?"))
      return response({
        reports: url.includes("monthly") ? [monthly] : [timeline],
        timezone: timeline.timezone,
        has_more: false,
      });
    return response({
      report: url.includes(monthly.id) ? monthly : timeline,
      revisions: [{ revision: 2 }, { revision: 1 }],
    });
  });
}
describe("Chronological report reading", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    window.history.replaceState({}, "", "/");
    mockTimeline();
  });
  it("renders the three approved sections and connects dated work to its final state", async () => {
    mount();
    await screen.findByRole("heading", { name: timeline.content.title });
    const merges = screen.getByRole("region", { name: "Merged to main" });
    const work = screen.getByRole("region", {
      name: "How the work progressed",
    });
    const final = screen.getByRole("region", { name: "Final state at cutoff" });
    expect(
      within(merges).getByRole("region", { name: "Friday merges" })
    ).toBeInTheDocument();
    expect(within(merges).getByText("14:12")).toBeInTheDocument();
    expect(within(merges).getByText("13:55")).toBeInTheDocument();
    expect(
      within(merges).getAllByRole("button", { name: /^Sources for/ })
    ).toHaveLength(1);
    expect(within(merges).getByText("Sources (2)")).toBeInTheDocument();
    expect(within(work).getByText("Thursday, Nov 12")).toBeInTheDocument();
    expect(within(work).getAllByText("Friday, Nov 13").length).toBeGreaterThan(
      0
    );
    expect(
      within(final).getByText(
        /its effect on the failure pattern remains unconfirmed/
      )
    ).toBeInTheDocument();
    expect(screen.queryByText("View evidence")).not.toBeInTheDocument();
    const topic = within(work).getByText("NHL telemetry").closest("details")!;
    expect(topic).not.toHaveAttribute("open");
    fireEvent.click(within(topic).getByText("NHL telemetry"));
    expect(topic).toHaveAttribute("open");
  });
  it("opens scoped originals and safe Git links from grouped sources", async () => {
    const callbacks = mount();
    await screen.findByText(timeline.content.title);
    fireEvent.click(
      screen.getByRole("button", { name: "Sources for NBA SSE reliability" })
    );
    const dialog = await screen.findByRole("dialog", {
      name: "NBA SSE reliability",
    });
    expect(
      within(dialog).getAllByRole("link", { name: "Open on GitHub" })
    ).toHaveLength(1);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Open original" })
    );
    expect(callbacks.onOpenEvidence).toHaveBeenCalledWith(
      expect.objectContaining({ eventId: "evt", timezone: timeline.timezone })
    );
  });
  it("groups monthly merges and topic updates by ISO week with expandable days", async () => {
    const original = timeline.content.topics[0].updates[0];
    const monthly = {
      ...timeline,
      kind: "monthly",
      period_start: "2026-11-01",
      period_end: "2026-11-30",
      content: {
        ...timeline.content,
        topics: [
          {
            ...timeline.content.topics[0],
            updates: [
              { ...original, date: "2026-11-02" },
              ...timeline.content.topics[0].updates,
            ],
          },
        ],
      },
    };
    vi.mocked(apiFetch).mockImplementation(async (path) =>
      String(path).includes("/reports?")
        ? response({
            reports: [monthly],
            timezone: timeline.timezone,
            has_more: false,
          })
        : response({ report: monthly, revisions: [{ revision: 2 }] })
    );
    mount();
    await screen.findByText(timeline.content.title);
    const work = screen.getByRole("region", {
      name: "How the work progressed",
    });
    expect(within(work).getByText("Week of November 2")).toBeInTheDocument();
    expect(within(work).getByText("Week of November 9")).toBeInTheDocument();
    const daily = within(work)
      .getByText("Show daily updates (2)")
      .closest("details")!;
    expect(daily).not.toHaveAttribute("open");
    fireEvent.click(within(daily).getByText("Show daily updates (2)"));
    expect(daily).toHaveAttribute("open");
  });
  it("keeps old sections readable without fabricating a dated timeline", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) =>
      String(path).includes("/reports?")
        ? response({ reports: [weekly], timezone: "UTC", has_more: false })
        : response({ report: weekly, revisions: [{ revision: 2 }] })
    );
    mount();
    await screen.findByText(weekly.content.title);
    expect(screen.getByText("Still open")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Merged to main" })
    ).not.toBeInTheDocument();
    const overview = screen.getByText("Overview").closest("details")!;
    expect(overview).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Overview"));
    expect(overview).toHaveAttribute("open");
    expect(screen.getByText(weekly.content.summary)).toBeInTheDocument();
  });
  it("uses the revision deep link and rejects revisions outside the returned choices", async () => {
    window.history.replaceState(
      {},
      "",
      `/?report=${timeline.id}&report_kind=weekly&report_revision=1`
    );
    mount();
    await screen.findByText(timeline.content.title);
    expect(apiFetch).toHaveBeenCalledWith(
      expect.stringContaining("?revision=1")
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Revision" }), {
      target: { value: "999" },
    });
    expect(apiFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("revision=999")
    );
  });
  it("keeps published older periods selectable and pages beyond the current list", async () => {
    const old = {
      ...timeline,
      id: "44444444-4444-4444-8444-444444444444",
      period_start: "2026-11-02",
      period_end: "2026-11-08",
      content: { ...timeline.content, title: "Previous week" },
    };
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      const url = String(path);
      return url.includes("/reports?")
        ? response({
            reports: url.includes("offset=50") ? [old] : [timeline, old],
            timezone: timeline.timezone,
            has_more: !url.includes("offset=50"),
          })
        : response({
            report: url.includes(old.id) ? old : timeline,
            revisions: [{ revision: 2 }],
          });
    });
    mount();
    await screen.findByText(timeline.content.title);
    fireEvent.change(screen.getByLabelText("Choose report period"), {
      target: { value: old.id },
    });
    await screen.findByText("Previous week");
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith(
        expect.stringContaining("offset=50")
      )
    );
    expect(
      await screen.findByRole("button", { name: "Newer" })
    ).not.toBeDisabled();
  });
  it("shows a styled settings error while keeping the report readable", async () => {
    const regular = vi.mocked(apiFetch).getMockImplementation()!;
    vi.mocked(apiFetch).mockImplementation((path, options) => {
      if (options?.method === "PUT")
        return Promise.reject(new Error("Could not update timezone."));
      if (String(path).includes("/reports?"))
        return Promise.resolve(
          response({ reports: [timeline], timezone: "UTC", has_more: false })
        );
      return regular(path, options);
    });
    mount();
    await screen.findByText(timeline.content.title);
    fireEvent.click(screen.getByRole("button", { name: "Use my timezone" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not update timezone."
    );
    expect(screen.getByText(timeline.content.title)).toBeInTheDocument();
  });
  it("moves keyboard focus to the requested report section", async () => {
    const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
    mount();
    await screen.findByText(timeline.content.title);
    fireEvent.click(screen.getByRole("button", { name: "Work timeline" }));
    expect(
      screen.getByRole("region", { name: "How the work progressed" })
    ).toHaveFocus();
    expect(scroll).toHaveBeenCalledWith({ block: "start" });
    scroll.mockRestore();
  });
  it("does not style a negated merge status as completed work", async () => {
    const report = {
      ...timeline,
      content: {
        ...timeline.content,
        topics: [
          {
            ...timeline.content.topics[0],
            final_state: {
              ...timeline.content.topics[0].final_state,
              status: "Not merged",
            },
          },
        ],
      },
    };
    vi.mocked(apiFetch).mockImplementation(async (path) =>
      String(path).includes("/reports?")
        ? response({
            reports: [report],
            timezone: report.timezone,
            has_more: false,
          })
        : response({ report, revisions: [{ revision: 2 }] })
    );
    mount();
    await screen.findByText(timeline.content.title);
    expect(screen.getByText("Not merged")).not.toHaveClass(
      "reports-tag-merged"
    );
  });
  it("keeps a January update in its ISO week spanning the previous year", async () => {
    const report = {
      ...timeline,
      kind: "monthly",
      period_start: "2027-01-01",
      period_end: "2027-01-31",
      content: {
        ...timeline.content,
        merges: [],
        topics: [
          {
            ...timeline.content.topics[0],
            updates: [
              { ...timeline.content.topics[0].updates[0], date: "2027-01-01" },
              { ...timeline.content.topics[0].updates[1], date: "2027-01-04" },
            ],
          },
        ],
      },
    };
    vi.mocked(apiFetch).mockImplementation(async (path) =>
      String(path).includes("/reports?")
        ? response({
            reports: [report],
            timezone: report.timezone,
            has_more: false,
          })
        : response({ report, revisions: [{ revision: 2 }] })
    );
    mount();
    await screen.findByText(timeline.content.title);
    const work = screen.getByRole("region", {
      name: "How the work progressed",
    });
    expect(within(work).getByText("Week of December 28")).toBeInTheDocument();
    expect(within(work).getByText("Week of January 4")).toBeInTheDocument();
  });
});
