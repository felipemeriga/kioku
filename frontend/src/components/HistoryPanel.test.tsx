import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import * as api from "../lib/api";
import { ApiError } from "../lib/api";
import LearningsPanel from "./LearningsPanel";
import type { EvidenceLocation } from "../lib/agentEvidenceApi";
const auth = vi.hoisted(() => ({ id: "history-user" as string | undefined }));
vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: auth.id ? { id: auth.id } : null }),
}));
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
vi.mock("./evidence/EvidenceDrawer", () => ({
  default: ({
    location,
    onClose,
  }: {
    location: EvidenceLocation | null;
    onClose: () => void;
  }) =>
    location ? (
      <section
        aria-label="Mock original reader"
        data-session={location.sessionId}
        data-date={location.date}
        data-event={location.eventId}
      >
        <button onClick={onClose}>Close test reader</button>
      </section>
    ) : null,
}));
const now = new Date();
const prefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(
  2,
  "0"
)}`;
const date = `${prefix}-04`;
const originalOnlyDate = `${prefix}-05`;
const native = "019a7150-5887-7000-8000-123456789abc";
const time = new Date(`${date}T10:00:00`).getTime();
const markdown = `## 10:00 — Codex\n<!-- kioku-entry: {"id":"entry-one","agent":"codex","session_id":"${native}","captured_at":${time}} -->\n\n## Findings\n\n- Preserved **journal text** and \`inline code\`.\n\n\`\`\`rust\nfn main() { println!("safe"); }\n\`\`\`\n`;
const original = {
  id: "server-root",
  agent: "codex",
  native_session_id: native,
  parent_session_id: null,
  root_session_id: "server-root",
  first_event_at: `${date}T10:00:00Z`,
  last_event_at: `${originalOnlyDate}T12:00:00Z`,
  manifest_revision: 2,
  indexed_revision: 2,
  capture_status: "captured",
  index_status: "ready",
  event_count: 100,
  active_day_count: 8,
  children: [],
  gaps: [],
  title: "Original title",
  day_first_event_at: `${date}T10:00:00Z`,
  day_last_event_at: `${date}T12:00:00Z`,
  day_event_count: 12,
  day_first_event_id: "first-event",
  day_first_session_id: "child-server",
};
function json(body: unknown) {
  return new Response(JSON.stringify(body));
}
let unavailable = false;
let cursor = false;
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  auth.id = "history-user";
  unavailable = false;
  cursor = false;
  Object.defineProperty(window, "sessionStorage", {
    value: storage(),
    configurable: true,
  });
  vi.spyOn(api, "apiFetch").mockImplementation(async (path) => {
    const url = String(path);
    if (url.includes("agent-history")) {
      if (unavailable)
        throw new ApiError({ status: 503, userMessage: "Unavailable" });
      if (url.includes("/days?"))
        return json({
          days: [
            { date, session_count: 1, event_count: 12, agents: ["codex"] },
            {
              date: originalOnlyDate,
              session_count: 2,
              event_count: 24,
              agents: ["codex", "claude_code"],
            },
          ],
          timezone: "UTC",
        });
      if (url.includes(`date=${originalOnlyDate}`))
        return json({
          sessions: [
            original,
            {
              ...original,
              id: "second-root",
              agent: "claude_code",
              native_session_id: "opaque-native",
              title: "Original-only task",
              day_first_event_id: "later-event",
              day_first_session_id: null,
            },
          ],
          next_cursor: null,
        });
      if (url.includes(`date=${date}`))
        return json({
          sessions: [original],
          next_cursor: cursor && !url.includes("cursor=") ? "next-page" : null,
        });
      return json({ sessions: [], next_cursor: null });
    }
    if (url.includes("learning-days/"))
      return url.includes(`/learning-days/${date}?`)
        ? json({
            status: "ok",
            markdown,
            revision: 1,
            sessions: [
              {
                agent: "codex",
                session_id: native,
                title: "Journal title",
                summary: "Existing summary",
                computer_name: "Laptop",
                entry_count: 1,
                first_time: time,
                last_time: time,
              },
            ],
          })
        : json({ status: "absent", markdown: "", revision: 0, sessions: [] });
    if (url.includes("learning-days?"))
      return json({
        days: [
          {
            journal_date: date,
            revision: 1,
            entry_count: 1,
            agents: ["codex"],
          },
        ],
      });
    if (url.includes("evidence-for-entry")) return json({ status: "absent" });
    if (url.endsWith("/learnings")) return json({ learnings: [] });
    throw Error("Unexpected request " + url);
  });
});
function storage() {
  const data: Record<string, string> = {};
  return new Proxy(
    {
      getItem: (k: string) => data[k] ?? null,
      setItem: (k: string, v: string) => {
        data[k] = v;
      },
      removeItem: (k: string) => {
        delete data[k];
      },
      clear: () => {
        Object.keys(data).forEach((k) => delete data[k]);
      },
    },
    {
      ownKeys: () => Object.keys(data),
      getOwnPropertyDescriptor: () => ({
        enumerable: true,
        configurable: true,
      }),
      get: (target, key) =>
        key in target ? Reflect.get(target, key) : data[String(key)],
    }
  );
}
async function journalDay() {
  fireEvent.click(
    await screen.findByRole("button", {
      name: new RegExp("4, .*1 journal entries"),
    })
  );
}
describe("unified History", () => {
  it("defaults to History+Learnings and merges both activity indices without duplicate session cards", async () => {
    renderWithProviders(<LearningsPanel folderId="repo" />);
    expect(screen.getAllByRole("tab").map((x) => x.textContent)).toEqual([
      "History",
      "Learnings",
    ]);
    await journalDay();
    expect(
      await screen.findAllByRole("button", { name: /Journal title/ })
    ).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Original title/ })).toBeNull();
    expect(
      screen.getByRole("button", { name: /5, .*24 original events/ })
    ).toBeInTheDocument();
  });
  it("shows originals-only on their active day and routes a child-only source anchor", async () => {
    renderWithProviders(<LearningsPanel folderId="repo" />);
    expect(await screen.findByText("Original-only task")).toBeInTheDocument();
    expect(screen.getAllByText("No journal summary yet.")).toHaveLength(2);
    fireEvent.click(
      within(screen.getByText("Original title").closest("article")!).getByRole(
        "button",
        { name: "View originals" }
      )
    );
    expect(
      screen.getByRole("region", { name: "Mock original reader" })
    ).toHaveAttribute("data-session", "child-server");
    expect(
      screen.getByRole("region", { name: "Mock original reader" })
    ).toHaveAttribute("data-date", originalOnlyDate);
    expect(
      screen.getByRole("region", { name: "Mock original reader" })
    ).toHaveAttribute("data-event", "first-event");
  });
  it("opens journal overview/timeline through the shared renderer while Markdown source stays exact", async () => {
    renderWithProviders(<LearningsPanel folderId="repo" />);
    await journalDay();
    fireEvent.click(
      await screen.findByRole("button", { name: /Journal title/ })
    );
    expect(
      screen.getByRole("region", { name: "Session overview" })
    ).toHaveTextContent("Existing summary");
    expect(
      screen.getByRole("heading", { name: "Findings" })
    ).toBeInTheDocument();
    expect(
      document.querySelector(".learnings-entry pre code")
    ).toHaveTextContent('fn main() { println!("safe"); }');
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(document.querySelector(".learnings-raw")?.textContent).toBe(
      markdown
    );
    fireEvent.click(screen.getByRole("button", { name: "Timeline" }));
    expect(
      screen.getByRole("heading", { name: "Findings" })
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View evidence" }));
    expect(
      screen.getByRole("region", { name: "Mock original reader" })
    ).toHaveAttribute("data-session", "child-server");
  });
  it("retains journal-only summaries with unavailable archival service and gentle evidence feedback", async () => {
    unavailable = true;
    renderWithProviders(<LearningsPanel folderId="repo" />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Journal title/ })
    );
    expect(
      await screen.findByText(/Original activity is currently unavailable/)
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View evidence" }));
    expect(
      await screen.findByText(
        "Original evidence is unavailable for this entry."
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Mock original reader" })
    ).toBeNull();
  });
  it("fetches month-local bounded dates and explicit day pages and leaves idle days empty", async () => {
    renderWithProviders(<LearningsPanel folderId="repo" />);
    await screen.findByText("Original-only task");
    fireEvent.click(
      screen.getByRole("button", {
        name: new RegExp(`\\b6, ${now.getFullYear()}, no entries`),
      })
    );
    expect(
      await screen.findByText("No history recorded on this day.")
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }));
    await waitFor(() =>
      expect(
        vi
          .mocked(api.apiFetch)
          .mock.calls.some(
            ([p]) =>
              String(p).includes("agent-history/days?start=") &&
              !String(p).includes(`start=${prefix}`)
          )
      ).toBe(true)
    );
    const urls = vi.mocked(api.apiFetch).mock.calls.map(([p]) => String(p));
    expect(
      urls
        .filter((u) => u.includes("agent-history/days"))
        .every((u) => u.includes("timezone=") && u.includes("&end="))
    ).toBe(true);
  });
  it("restores selected History day/session and its owning main scroll without repeated resets", async () => {
    const first = renderWithProviders(
      <main>
        <LearningsPanel folderId="repo" />
      </main>
    );
    await journalDay();
    fireEvent.click(
      await screen.findByRole("button", { name: /Journal title/ })
    );
    document.querySelector("main")!.scrollTop = 240;
    fireEvent.click(screen.getByRole("button", { name: "View evidence" }));
    const key = "kioku.evidence-journal-return:history-user:repo";
    const saved = JSON.parse(sessionStorage.getItem(key)!);
    expect(saved).toMatchObject({
      selectedDate: date,
      selectedSession: { date, key: `codex:${native}` },
      scrollY: 240,
      scrollOwner: "container",
      view: "history",
    });
    first.unmount();
    renderWithProviders(
      <main>
        <LearningsPanel folderId="repo" />
      </main>
    );
    await screen.findByRole("region", { name: "Session overview" });
    await waitFor(() =>
      expect(document.querySelector("main")!.scrollTop).toBe(240)
    );
    expect(sessionStorage.getItem(key)).toBeNull();
  });
  it("normalizes legacy Originals state and devalidates selection on folder/auth changes", async () => {
    sessionStorage.setItem(
      "kioku.evidence-journal-return:history-user:repo",
      JSON.stringify({
        year: now.getFullYear(),
        month: now.getMonth(),
        view: "originals",
        selectedDate: originalOnlyDate,
        selectedSession: null,
        raw: false,
        scrollY: 0,
        savedAt: Date.now(),
      })
    );
    const rendered = renderWithProviders(<LearningsPanel folderId="repo" />);
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await screen.findByText("Original-only task");
    rendered.rerender(<LearningsPanel folderId="other" />);
    await waitFor(() =>
      expect(
        sessionStorage.getItem(
          "kioku.evidence-journal-return:history-user:repo"
        )
      ).toBeNull()
    );
    auth.id = undefined;
    rendered.rerender(<LearningsPanel folderId="other" />);
    expect(screen.getByRole("tab", { name: "History" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });
  it("loads additional original metadata using the selected day's opaque cursor", async () => {
    cursor = true;
    renderWithProviders(<LearningsPanel folderId="repo" />);
    await journalDay();
    fireEvent.click(
      await screen.findByRole("button", { name: "Load more sessions" })
    );
    await waitFor(() =>
      expect(
        vi
          .mocked(api.apiFetch)
          .mock.calls.some(([p]) => String(p).includes("cursor=next-page"))
      ).toBe(true)
    );
    expect(
      screen.getAllByRole("button", { name: /Journal title/ })
    ).toHaveLength(1);
  });
  it("opens a journal search match and returns with query preserved", async () => {
    const originalMock = vi.mocked(api.apiFetch).getMockImplementation()!;
    vi.mocked(api.apiFetch).mockImplementation(async (path, options) => {
      if (String(path).includes("history-search?"))
        return json({
          total_sessions: 1,
          total_entries: 1,
          has_more: false,
          sessions: [
            {
              agent: "codex",
              session_id: native,
              title: "Search result title",
              dates: [date],
              title_match: false,
              overview_match: false,
              matches: [
                { id: "entry-one", date, excerpt: "Preserved journal text" },
              ],
            },
          ],
        });
      return originalMock(path, options);
    });
    renderWithProviders(<LearningsPanel folderId="repo" />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search history" }), {
      target: { value: "journal" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(
      await screen.findByRole("button", { name: /Preserved journal text/ })
    );
    await screen.findByRole("region", { name: "Session overview" });
    fireEvent.click(screen.getByRole("button", { name: /Search results/ }));
    await screen.findByRole("button", { name: /Search result title/ });
    expect(screen.getByRole("textbox", { name: "Search history" })).toHaveValue(
      "journal"
    );
  });
});
