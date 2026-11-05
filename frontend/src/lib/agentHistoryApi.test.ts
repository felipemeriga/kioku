import { describe, expect, it, vi, beforeEach } from "vitest";
import * as api from "./api";
import {
  fetchHistoryDays,
  fetchHistorySessions,
  historyEvidenceLocation,
  monthBounds,
  unionHistorySessions,
  type OriginalHistorySession,
  type JournalHistorySession,
} from "./agentHistoryApi";
vi.mock("./supabase", () => ({ supabase: { auth: { getSession: vi.fn() } } }));
const original: OriginalHistorySession = {
  id: "root-archive",
  agent: "codex",
  native_session_id: "native-root",
  parent_session_id: null,
  root_session_id: "root-archive",
  first_event_at: null,
  last_event_at: null,
  manifest_revision: 2,
  indexed_revision: 2,
  capture_status: "captured",
  index_status: "ready",
  event_count: 99,
  active_day_count: 8,
  children: [],
  gaps: [],
  day_first_event_at: "2026-11-04T10:00:00Z",
  day_last_event_at: "2026-11-04T11:00:00Z",
  day_event_count: 12,
  day_first_event_id: "first-child-event",
  day_first_session_id: "child-archive",
};
const journal: JournalHistorySession = {
  agent: "codex",
  session_id: "native-root",
  title: "Journal title",
  summary: "Keep original summary",
  computer_name: "Laptop",
  entry_count: 3,
  first_time: 123,
  last_time: 456,
};
beforeEach(() => vi.restoreAllMocks());
describe("original history API and union", () => {
  it("bounds months by local dates including leap February and year rollover", () => {
    expect(monthBounds(2024, 1)).toEqual({
      start: "2024-02-01",
      end: "2024-02-29",
    });
    expect(monthBounds(2026, 11)).toEqual({
      start: "2026-12-01",
      end: "2026-12-31",
    });
  });
  it("fetches only the selected month and timezone with scoped folder and cancellation", async () => {
    const mock = vi
      .spyOn(api, "apiFetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ days: [], timezone: "America/Sao_Paulo" }),
        ),
      );
    const signal = new AbortController().signal;
    await fetchHistoryDays("repo/id", 2026, 10, "America/Sao_Paulo", signal);
    expect(mock).toHaveBeenCalledWith(
      "/api/folders/repo%2Fid/agent-history/days?start=2026-11-01&end=2026-11-30&timezone=America%2FSao_Paulo",
      { signal },
    );
  });
  it("pages only one selected local day with opaque cursors", async () => {
    const mock = vi
      .spyOn(api, "apiFetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ sessions: [], next_cursor: null })),
      );
    await fetchHistorySessions("repo", "2026-11-05", "UTC", "opaque/+next");
    expect(mock).toHaveBeenCalledWith(
      expect.stringContaining(
        "date=2026-11-05&timezone=UTC&limit=50&cursor=opaque%2F%2Bnext",
      ),
      { signal: undefined },
    );
  });
  it("deduplicates matching identities while preserving summary and captured journal timestamps", () => {
    const merged = unionHistorySessions([journal], [original, original]);
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      ...journal,
      hasJournal: true,
      originals: original,
    });
  });
  it("keeps journal-only and original-only sessions separate across agents", () => {
    const merged = unionHistorySessions(
      [journal],
      [{ ...original, agent: "claude_code" }],
    );
    expect(merged).toHaveLength(2);
    expect(merged.find((x) => x.agent === "claude_code")).toMatchObject({
      hasJournal: false,
      entry_count: 0,
      summary: "",
      session_id: "native-root",
    });
    expect(merged.find((x) => x.agent === "codex")?.originals).toBeUndefined();
  });
  it("opens child-only activity by actual child/event while preserving selected day/timezone", () => {
    expect(
      historyEvidenceLocation(
        "folder",
        original,
        "2026-11-04",
        "Pacific/Auckland",
      ),
    ).toEqual({
      folderId: "folder",
      sessionId: "child-archive",
      eventId: "first-child-event",
      date: "2026-11-04",
      timezone: "Pacific/Auckland",
      mode: "conversation",
    });
    expect(
      historyEvidenceLocation(
        "folder",
        { ...original, day_first_event_id: null, day_first_session_id: null },
        "2026-11-05",
        "UTC",
      ),
    ).toMatchObject({
      sessionId: "root-archive",
      date: "2026-11-05",
      eventId: undefined,
    });
  });
});
