import { apiFetch } from "./api";
import type { EvidenceLocation, EvidenceSession } from "./agentEvidenceApi";

export interface OriginalHistoryDay {
  date: string;
  session_count: number;
  event_count: number;
  agents: string[];
}
export type OriginalHistorySession = EvidenceSession & {
  day_first_event_at: string | null;
  day_last_event_at: string | null;
  day_event_count: number;
  day_first_event_id: string | null;
  day_first_session_id: string | null;
};
export interface JournalHistorySession {
  agent: string;
  session_id: string;
  title: string;
  summary: string;
  computer_name: string;
  entry_count: number;
  first_time: number;
  last_time: number;
}
export type HistorySession = JournalHistorySession & {
  hasJournal: boolean;
  originals?: OriginalHistorySession;
};
export const historyIdentity = (agent: string, native: string) =>
  `${agent}:${native}`;
export function monthBounds(year: number, month: number) {
  const prefix = `${year}-${String(month + 1).padStart(2, "0")}`;
  return {
    start: `${prefix}-01`,
    end: `${prefix}-${new Date(year, month + 1, 0).getDate()}`,
  };
}
const base = (folder: string) =>
  `/api/folders/${encodeURIComponent(folder)}/agent-history`;
export async function fetchHistoryDays(
  folder: string,
  year: number,
  month: number,
  timezone: string,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ ...monthBounds(year, month), timezone });
  const response = await apiFetch(`${base(folder)}/days?${params}`, { signal });
  return response.json() as Promise<{
    days: OriginalHistoryDay[];
    timezone: string;
  }>;
}
export async function fetchHistorySessions(
  folder: string,
  date: string,
  timezone: string,
  cursor?: string,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams({ date, timezone, limit: "50" });
  if (cursor) params.set("cursor", cursor);
  const response = await apiFetch(`${base(folder)}/sessions?${params}`, {
    signal,
  });
  return response.json() as Promise<{
    sessions: OriginalHistorySession[];
    next_cursor: string | null;
    timezone: string;
    date: string;
  }>;
}
/** Journal capture time is preserved; only identities are joined, never body text. */
export function unionHistorySessions(
  journals: JournalHistorySession[],
  originals: OriginalHistorySession[],
): HistorySession[] {
  const merged = new Map<string, HistorySession>();
  for (const session of journals)
    merged.set(historyIdentity(session.agent, session.session_id), {
      ...session,
      hasJournal: true,
    });
  for (const original of originals) {
    const key = historyIdentity(original.agent, original.native_session_id);
    const journal = merged.get(key);
    merged.set(
      key,
      journal
        ? { ...journal, originals: original }
        : {
            agent: original.agent,
            session_id: original.native_session_id,
            title: original.title || "Original session",
            summary: "",
            computer_name: "",
            entry_count: 0,
            first_time: original.day_first_event_at
              ? Date.parse(original.day_first_event_at)
              : 0,
            last_time: original.day_last_event_at
              ? Date.parse(original.day_last_event_at)
              : 0,
            hasJournal: false,
            originals: original,
          },
    );
  }
  return [...merged.values()].sort(
    (a, b) =>
      a.first_time - b.first_time ||
      historyIdentity(a.agent, a.session_id).localeCompare(
        historyIdentity(b.agent, b.session_id),
      ),
  );
}
export function historyEvidenceLocation(
  folderId: string,
  session: OriginalHistorySession,
  date: string,
  timezone: string,
): EvidenceLocation {
  return {
    folderId,
    sessionId: session.day_first_session_id || session.id,
    date,
    timezone,
    mode: "conversation",
    eventId: session.day_first_event_id || undefined,
  };
}
