import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { ReadableContent } from "./agent-evidence/ReadableContent";
import { apiFetch } from "../lib/api";
import { brand, fonts } from "../theme";
import "./LearningsPanel.css";
import ReportsPanel from "./ReportsPanel";
import { HistorySearchToolbar, HistorySearchResults } from "./HistorySearch";
import {
  emptyHistoryFilters,
  hasHistoryFilters,
  type HistoryFilters,
} from "../lib/historySearch";
import { useAuth } from "../hooks/useAuth";
import type { EvidenceLocation } from "../lib/agentEvidenceApi";
import EvidenceDrawer from "./evidence/EvidenceDrawer";
import PanelResizeHandle from "./PanelResizeHandle";
import { usePanelSize } from "../hooks/usePanelSize";
import JournalEvidenceLink from "./evidence/JournalEvidenceLink";
import {
  historyEvidenceLocation,
  historyIdentity,
  unionHistorySessions,
  type JournalHistorySession,
} from "../lib/agentHistoryApi";
import {
  useOriginalHistoryDays,
  useOriginalHistorySessions,
  historyUnsupported,
} from "../hooks/useAgentHistory";

type JournalReturnState = {
  year: number;
  month: number;
  selectedDate: string | null;
  selectedSession: { date: string; key: string } | null;
  raw: boolean;
  view: "history" | "journal" | "learnings" | "originals" | "reports";
  scrollOwner?: "container" | "main" | "window";
  listScroll?: number;
  scrollY: number;
  savedAt: number;
  searchFilters?: HistoryFilters;
  searchDetail?: boolean;
};
function readJournalReturn(key: string): JournalReturnState | null {
  try {
    const value = JSON.parse(
      sessionStorage.getItem(key) || "null"
    ) as JournalReturnState | null;
    if (
      !value ||
      !Number.isInteger(value.year) ||
      !Number.isInteger(value.month) ||
      value.month < 0 ||
      value.month > 11 ||
      Date.now() - value.savedAt > 600_000 ||
      !["history", "journal", "learnings", "originals", "reports"].includes(
        value.view
      )
    )
      return null;
    return value;
  } catch {
    return null;
  }
}

type JournalDay = {
  journal_date: string;
  revision: number;
  entry_count: number;
  agents: string[];
  approximate?: boolean;
};
type Entry = {
  id: string;
  agent: string;
  sessionId: string;
  sessionKey: string;
  computerName: string;
  time: number;
  markdown: string;
};
type JournalSession = JournalHistorySession;
const SESSION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function entriesFromMarkdown(markdown: string): Entry[] {
  const headings = [
    ...markdown.matchAll(
      /^## (?:Codex|Claude Code) session [^\n]+\n|^#{2,3} (\d\d:\d\d|\d{13}) — ([^\n]+)\n/gm
    ),
  ];
  const entries: Entry[] = [];
  for (let i = 0; i < headings.length; i++) {
    const heading = headings[i];
    if (!heading[1]) continue;
    const section = markdown.slice(
      heading.index! + heading[0].length,
      i + 1 < headings.length ? headings[i + 1].index! : markdown.length
    );
    const marker = section.match(/^<!-- kioku-entry: (\{[^\n]+\}) -->\n/m);
    if (!marker) continue;
    try {
      const meta = JSON.parse(marker[1]) as {
        id: string;
        agent: string;
        session_id?: string;
        computer_name?: string;
        captured_at?: number | string;
      };
      const time =
        typeof meta.captured_at === "number"
          ? meta.captured_at
          : Date.parse(meta.captured_at ?? "");
      if (!Number.isFinite(time)) continue;
      entries.push({
        id: meta.id,
        agent: meta.agent,
        sessionKey: `${meta.agent}:${meta.session_id ?? meta.id}`,
        sessionId:
          typeof meta.session_id === "string" &&
          SESSION_UUID.test(meta.session_id)
            ? meta.session_id
            : "",
        time,
        computerName:
          typeof meta.computer_name === "string" ? meta.computer_name : "",
        markdown: section.replace(marker[0], "").trim(),
      });
    } catch {
      /* An invalid entry stays visible in raw Markdown. */
    }
  }
  return entries.sort((a, b) => a.time - b.time);
}

function localDay(epochMs: number) {
  const date = new Date(epochMs);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(
    2,
    "0"
  )}-${String(date.getDate()).padStart(2, "0")}`;
}

function localTime(epochMs: number) {
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(epochMs));
}

function dateLabel(day: string) {
  const [year, month, date] = day.split("-").map(Number);
  return new Intl.DateTimeFormat("en", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date(year, month - 1, date));
}

function historyScrollContainer(panel: HTMLElement | null): HTMLElement | null {
  let node = panel?.parentElement ?? null;
  while (node && node !== document.body && node !== document.documentElement) {
    if (/auto|scroll/.test(getComputedStyle(node).overflowY)) return node;
    node = node.parentElement;
  }
  return panel?.closest("main") ?? null;
}
export default function LearningsPanel({ folderId }: { folderId: string }) {
  const { user } = useAuth();
  return (
    <HistoryPanel
      key={`${user?.id ?? "anonymous"}:${folderId}`}
      folderId={folderId}
    />
  );
}
function HistoryPanel({ folderId }: { folderId: string }) {
  const calendarSize = usePanelSize("calendar", 276, 220, 380, 600);
  const { user } = useAuth();
  const returnKey = `kioku.evidence-journal-return:${
    user?.id ?? "anonymous"
  }:${folderId}`;
  const [restored] = useState(() =>
    user ? readJournalReturn(returnKey) : null
  );
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [view, setView] = useState<"history" | "reports">(
    new URLSearchParams(window.location.search).has("report") ||
      restored?.view === "reports"
      ? "reports"
      : "history"
  );
  const [searchFilters, setSearchFilters] = useState<HistoryFilters>(
    restored?.searchFilters ?? { ...emptyHistoryFilters }
  );
  const [searchDetail, setSearchDetail] = useState(
    restored?.searchDetail ?? false
  );
  const searching = hasHistoryFilters(searchFilters) && !searchDetail;
  const [showSearchDates, setShowSearchDates] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const scrollRestored = useRef(false);
  const listScroll = useRef(restored?.listScroll ?? 0);
  const currentScroll = () =>
    historyScrollContainer(panel.current)?.scrollTop ?? window.scrollY;
  const restoreScroll = (top: number) =>
    requestAnimationFrame(() => {
      const main = historyScrollContainer(panel.current);
      if (main) main.scrollTop = top;
      else window.scrollTo({ top });
    });
  const [month, setMonth] = useState(
    () => restored?.month ?? new Date().getMonth()
  );
  const [year, setYear] = useState(
    () => restored?.year ?? new Date().getFullYear()
  );
  const [selectedDate, setSelectedDate] = useState<string | null>(
    restored?.selectedDate ?? null
  );
  const [raw, setRaw] = useState(restored?.raw ?? false);
  const [selectedSession, setSelectedSession] = useState<{
    date: string;
    key: string;
  } | null>(restored?.selectedSession ?? null);
  const [pendingEntry, setPendingEntry] = useState<string | null>(null);
  const [evidenceLocation, setEvidenceLocation] =
    useState<EvidenceLocation | null>(null);
  const saveReturn = () => {
    if (!user) return;
    try {
      sessionStorage.setItem(
        returnKey,
        JSON.stringify({
          year,
          month,
          selectedDate: selectedDate ?? activeDate,
          selectedSession,
          raw,
          view,
          scrollY: currentScroll(),
          listScroll: listScroll.current,
          scrollOwner: historyScrollContainer(panel.current)
            ? "container"
            : "window",
          savedAt: Date.now(),
          searchFilters,
          searchDetail,
        })
      );
    } catch {
      /* Optional browser UI storage. */
    }
  };
  const openEvidence = (location: EvidenceLocation) => {
    saveReturn();
    setEvidenceLocation(location);
  };
  useEffect(() => {
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (
          key.startsWith("kioku.evidence-journal-return:") &&
          (!user || key !== returnKey)
        )
          sessionStorage.removeItem(key);
      }
    } catch {
      /* Browser storage is optional. */
    }
  }, [returnKey, user]);

  const daysQuery = useQuery({
    queryKey: ["learning-days", folderId, user?.id, year, month, timezone],
    queryFn: async () =>
      (await (
        await apiFetch(
          `/api/folders/${folderId}/learning-days?year=${year}&month=${
            month + 1
          }&timezone=${encodeURIComponent(timezone)}`
        )
      ).json()) as { days: JournalDay[] },
    staleTime: 60_000,
    enabled: view === "history",
    retry: 1,
  });
  const originalDays = useOriginalHistoryDays(
    folderId,
    user?.id,
    year,
    month,
    timezone,
    view === "history"
  );
  const dayMap = useMemo(() => {
    const map = new Map(
      (daysQuery.data?.days ?? []).map((day) => [
        day.journal_date,
        { ...day, event_count: 0, session_count: 0 },
      ])
    );
    for (const day of originalDays.data?.days ?? []) {
      const journal = map.get(day.date);
      map.set(day.date, {
        journal_date: day.date,
        revision: journal?.revision ?? 0,
        entry_count: journal?.entry_count ?? 0,
        agents: [...new Set([...(journal?.agents ?? []), ...day.agents])],
        approximate: journal?.approximate,
        event_count: day.event_count,
        session_count: day.session_count,
      });
    }
    return map;
  }, [daysQuery.data, originalDays.data]);
  const activeDate =
    selectedDate ?? [...dayMap.keys()].sort().reverse()[0] ?? null;
  const originalSessions = useOriginalHistorySessions(
    folderId,
    user?.id,
    activeDate,
    timezone,
    view === "history" && !historyUnsupported(originalDays.error)
  );
  const dayQuery = useQuery({
    queryKey: ["learning-day", folderId, user?.id, activeDate, timezone],
    queryFn: async () =>
      (await (
        await apiFetch(
          `/api/folders/${folderId}/learning-days/${activeDate}?timezone=${encodeURIComponent(
            timezone
          )}`
        )
      ).json()) as {
        status: string;
        markdown: string;
        revision: number;
        sessions?: JournalSession[];
      },
    enabled: !!activeDate && view === "history",
    staleTime: 30_000,
    retry: 1,
  });

  useEffect(() => {
    if (
      restored &&
      !scrollRestored.current &&
      (view !== "history" ||
        (dayQuery.isFetched &&
          (originalSessions.isFetched ||
            historyUnsupported(originalDays.error))))
    ) {
      scrollRestored.current = true;
      try {
        sessionStorage.removeItem(returnKey);
      } catch {
        /* Optional UI storage. */
      }
      requestAnimationFrame(() => {
        const main = historyScrollContainer(panel.current);
        if (
          (restored.scrollOwner === "main" ||
            restored.scrollOwner === "container") &&
          main
        )
          main.scrollTop = restored.scrollY;
        else window.scrollTo({ top: restored.scrollY });
      });
    }
  }, [
    restored,
    dayQuery.isFetched,
    originalSessions.isFetched,
    originalDays.error,
    view,
    returnKey,
  ]);

  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7;
  const count = new Date(year, month + 1, 0).getDate();
  const calendarCells = Array.from(
    { length: firstWeekday + count },
    (_, i) => i - firstWeekday + 1
  );
  const monthLabel = new Intl.DateTimeFormat("en", {
    month: "long",
    year: "numeric",
  }).format(new Date(year, month, 1));
  const entries = entriesFromMarkdown(dayQuery.data?.markdown ?? "");
  const journalSessions =
    dayQuery.data?.sessions ??
    Array.from(
      entries
        .reduce((groups, entry) => {
          const current = groups.get(entry.sessionKey);
          if (current) current.entry_count += 1;
          else
            groups.set(entry.sessionKey, {
              agent: entry.agent,
              session_id: entry.sessionKey.slice(entry.agent.length + 1),
              title:
                entry.markdown
                  .split("\n")[0]
                  .replace(/^[#*\-\s]+/, "")
                  .slice(0, 120) || "Untitled session",
              summary: "",
              computer_name: entry.computerName,
              entry_count: 1,
              first_time: entry.time,
              last_time: entry.time,
            });
          return groups;
        }, new Map<string, JournalSession>())
        .values()
    );
  const sessions = unionHistorySessions(
    journalSessions,
    originalSessions.data?.pages.flatMap((page) => page.sessions ?? []) ?? []
  );
  const activeSession =
    selectedSession?.date === activeDate
      ? sessions.find(
          (session) =>
            session.hasJournal &&
            `${session.agent}:${session.session_id}` === selectedSession.key
        )
      : undefined;
  const visibleEntries = activeSession
    ? entries.filter((entry) => entry.sessionKey === selectedSession?.key)
    : [];

  useEffect(() => {
    if (!pendingEntry || !dayQuery.isSuccess) return;
    const node = document.getElementById(`journal-entry-${pendingEntry}`);
    if (node) {
      node.scrollIntoView?.({ block: "center" });
      setPendingEntry(null);
    }
  }, [pendingEntry, dayQuery.isSuccess, activeSession]);

  const changeMonth = (step: number) => {
    const next = new Date(year, month + step, 1);
    setYear(next.getFullYear());
    setMonth(next.getMonth());
    setSelectedDate(null);
    setSelectedSession(null);
    setRaw(false);
  };
  const openSource = async (day: string, entryId?: string) => {
    let viewerDay = day;
    let targetEntry: Entry | undefined;
    if (entryId) {
      try {
        const response = await apiFetch(
          `/api/folders/${folderId}/learning-days/${day}`
        );
        const source = (await response.json()) as { markdown?: string };
        targetEntry = entriesFromMarkdown(source.markdown ?? "").find(
          (item) => item.id === entryId
        );
        if (targetEntry) viewerDay = localDay(targetEntry.time);
      } catch {
        /* Keep the source day navigable if the entry lookup fails. */
      }
    }
    const [y, m] = viewerDay.split("-").map(Number);
    setYear(y);
    setMonth(m - 1);
    setSelectedDate(viewerDay);
    setSelectedSession(
      targetEntry ? { date: viewerDay, key: targetEntry.sessionKey } : null
    );
    setPendingEntry(targetEntry?.id ?? null);
    setSearchFilters({ ...emptyHistoryFilters });
    setSearchDetail(false);
    setRaw(false);
    setView("history");
  };

  return (
    <Box className="learnings-panel" ref={panel}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "flex-start", sm: "center" }}
        gap={2}
        sx={{ mb: 2.5 }}
      >
        <Box>
          <Typography
            variant="h5"
            sx={{ fontFamily: fonts.display, fontWeight: 650 }}
          >
            Agents
          </Typography>
          <Typography sx={{ color: brand.muted, fontSize: 14 }}>
            Session history and periodic reports.
          </Typography>
        </Box>
        <Tabs
          value={view}
          onChange={(_, value) => setView(value)}
          aria-label="Memory views"
          sx={{
            minHeight: 38,
            "& .MuiTab-root": { minHeight: 38, textTransform: "none" },
          }}
        >
          <Tab value="history" label="History" />
          <Tab value="reports" label="Reports" />
        </Tabs>
      </Stack>

      {view === "history" ? (
        <>
          <HistorySearchToolbar
            filters={searchFilters}
            onChange={(filters) => {
              setSearchFilters(filters);
              setSearchDetail(false);
            }}
          />
          {searching && (
            <Button
              className="history-search-dates-toggle"
              onClick={() => setShowSearchDates(!showSearchDates)}
              aria-expanded={showSearchDates}
            >
              Dates
            </Button>
          )}
          <Box
            sx={{ "--history-calendar-width": `${calendarSize.size}px` }}
            className={`learnings-journal-layout ${
              searching ? "history-search-layout" : ""
            } ${showSearchDates ? "history-show-dates" : ""}`}
          >
            <Box
              id="history-calendar"
              className="learnings-calendar"
              aria-label="History calendar"
            >
              <Stack
                direction="row"
                alignItems="center"
                justifyContent="space-between"
                sx={{ mb: 1.5 }}
              >
                <Typography sx={{ fontWeight: 650, fontSize: 15 }}>
                  {monthLabel}
                </Typography>
                <Stack direction="row">
                  <IconButton
                    aria-label="Previous month"
                    size="small"
                    onClick={() => changeMonth(-1)}
                  >
                    <ChevronLeftIcon fontSize="small" />
                  </IconButton>
                  <IconButton
                    aria-label="Next month"
                    size="small"
                    onClick={() => changeMonth(1)}
                  >
                    <ChevronRightIcon fontSize="small" />
                  </IconButton>
                </Stack>
              </Stack>
              {daysQuery.isLoading && originalDays.isLoading ? (
                <CircularProgress size={22} aria-label="Loading journal days" />
              ) : daysQuery.isError && !originalDays.data?.days.length ? (
                <Alert
                  severity="error"
                  action={
                    <Button onClick={() => void daysQuery.refetch()}>
                      Retry
                    </Button>
                  }
                >
                  Could not load journal dates.
                </Alert>
              ) : (
                <>
                  <div
                    className="learnings-calendar-grid"
                    role="grid"
                    aria-label={monthLabel}
                  >
                    {["M", "T", "W", "T", "F", "S", "S"].map((label, index) => (
                      <span key={index} className="learnings-weekday">
                        {label}
                      </span>
                    ))}
                    {calendarCells.map((date, index) => {
                      if (date < 1) return <span key={`blank-${index}`} />;
                      const key = `${year}-${String(month + 1).padStart(
                        2,
                        "0"
                      )}-${String(date).padStart(2, "0")}`;
                      const day = dayMap.get(key);
                      return (
                        <button
                          key={key}
                          type="button"
                          className={`learnings-day ${
                            activeDate === key ? "selected" : ""
                          } ${day ? "has-entry" : ""}`}
                          aria-label={`${dateLabel(key)}${
                            day
                              ? `, ${day.approximate ? "at least " : ""}${
                                  day.entry_count
                                } journal entries, ${
                                  day.event_count
                                } original events`
                              : ", no entries"
                          }`}
                          aria-pressed={activeDate === key}
                          onClick={() => {
                            setSelectedDate(key);
                            if (hasHistoryFilters(searchFilters)) {
                              setSearchFilters({
                                ...searchFilters,
                                date_from: key,
                                date_to: key,
                              });
                              setSearchDetail(false);
                            }
                            setSelectedSession(null);
                            setRaw(false);
                          }}
                        >
                          <span>{date}</span>
                          <span className="learnings-day-dots">
                            {day?.agents.includes("claude_code") && (
                              <i className="claude" />
                            )}
                            {day?.agents.includes("codex") && (
                              <i className="codex" />
                            )}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                  <Stack
                    direction="row"
                    gap={2}
                    sx={{ mt: 2, color: brand.muted, fontSize: 12 }}
                  >
                    <span>
                      <i className="learnings-legend-dot claude" /> Claude
                    </span>
                    <span>
                      <i className="learnings-legend-dot codex" /> Codex
                    </span>
                  </Stack>
                </>
              )}
              <Typography className="history-calendar-note" variant="caption">
                {timezone}
              </Typography>
            </Box>

            <Box className="history-calendar-resizer">
              <PanelResizeHandle
                label="Resize history calendar"
                controls="history-calendar"
                {...calendarSize}
                onChange={calendarSize.setSize}
              />
            </Box>
            <Box className="learnings-timeline">
              {searching ? (
                <HistorySearchResults
                  key={JSON.stringify(searchFilters)}
                  folderId={folderId}
                  userId={user?.id}
                  timezone={timezone}
                  filters={searchFilters}
                  onOpen={(session, day, entryId) => {
                    if (!day) return;
                    const [y, m] = day.split("-").map(Number);
                    setYear(y);
                    setMonth(m - 1);
                    setSelectedDate(day);
                    setSelectedSession({
                      date: day,
                      key: historyIdentity(session.agent, session.session_id),
                    });
                    setRaw(false);
                    setSearchDetail(true);
                    if (entryId) setPendingEntry(entryId);
                  }}
                />
              ) : (
                <>
                  {searchDetail && (
                    <Button
                      size="small"
                      onClick={() => setSearchDetail(false)}
                      sx={{ mb: 2 }}
                    >
                      ← Search results
                    </Button>
                  )}
                  {(originalDays.isError || originalSessions.isError) && (
                    <Alert
                      severity={
                        historyUnsupported(originalDays.error) ||
                        historyUnsupported(originalSessions.error)
                          ? "info"
                          : "warning"
                      }
                      sx={{ mb: 2 }}
                      action={
                        <Button
                          onClick={() => {
                            void originalDays.refetch();
                            void originalSessions.refetch();
                          }}
                        >
                          Retry
                        </Button>
                      }
                    >
                      Original activity is currently unavailable. Journal
                      summaries remain available.
                    </Alert>
                  )}

                  {dayQuery.isError &&
                    originalSessions.data?.pages.some(
                      (page) => page.sessions.length
                    ) && (
                      <Alert
                        severity="warning"
                        sx={{ mb: 2 }}
                        action={
                          <Button onClick={() => void dayQuery.refetch()}>
                            Retry
                          </Button>
                        }
                      >
                        Journal summaries could not be loaded. Original activity
                        is still available.
                      </Alert>
                    )}
                  <Stack
                    direction="row"
                    alignItems="center"
                    justifyContent="space-between"
                    gap={1}
                    sx={{ mb: 2 }}
                  >
                    <Box>
                      <Typography sx={{ fontSize: 18, fontWeight: 650 }}>
                        {activeDate ? dateLabel(activeDate) : "Choose a day"}
                      </Typography>
                      {activeDate && (
                        <Typography sx={{ color: brand.muted, fontSize: 13 }}>
                          {dayQuery.data?.status === "ok"
                            ? entries.length
                            : dayMap.get(activeDate)?.approximate
                            ? `At least ${dayMap.get(activeDate)?.entry_count}`
                            : dayMap.get(activeDate)?.entry_count}{" "}
                          journal entries · {sessions.length}
                          {originalSessions.hasNextPage ? "+" : ""} sessions ·{" "}
                          {timezone}
                        </Typography>
                      )}
                    </Box>
                    {dayQuery.data?.status === "ok" && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => setRaw(!raw)}
                      >
                        {raw ? "Timeline" : "Markdown"}
                      </Button>
                    )}
                  </Stack>
                  {!activeDate ? (
                    <Typography sx={{ color: brand.muted }}>
                      Select a marked day to read the session history.
                    </Typography>
                  ) : dayQuery.isLoading ? (
                    <Stack direction="row" gap={1} alignItems="center">
                      <CircularProgress size={18} />
                      Loading journal…
                    </Stack>
                  ) : dayQuery.isError &&
                    !originalSessions.data?.pages.some(
                      (page) => page.sessions.length
                    ) ? (
                    <Alert
                      severity="error"
                      action={
                        <Button onClick={() => void dayQuery.refetch()}>
                          Retry
                        </Button>
                      }
                    >
                      Could not load this journal.
                    </Alert>
                  ) : raw && dayQuery.data?.status === "ok" ? (
                    <Box component="pre" className="learnings-raw">
                      {dayQuery.data.markdown}
                    </Box>
                  ) : !activeSession ? (
                    <div className="learnings-session-list">
                      {originalSessions.isLoading && (
                        <Typography role="status">
                          Loading original activity…
                        </Typography>
                      )}
                      {!sessions.length && !originalSessions.isLoading && (
                        <Typography sx={{ color: brand.muted }}>
                          No history recorded on this day.
                        </Typography>
                      )}
                      {sessions.map((session) =>
                        session.hasJournal ? (
                          <article
                            key={historyIdentity(
                              session.agent,
                              session.session_id
                            )}
                            className="learnings-session-card"
                            onClick={(event) => {
                              // Keep embedded links, controls, and text selection usable.
                              if (
                                event.defaultPrevented ||
                                !(event.target instanceof Element) ||
                                event.target.closest(
                                  "a, button, input, select, textarea, [role='button']"
                                )
                              )
                                return;
                              const selection = window.getSelection();
                              if (
                                selection &&
                                !selection.isCollapsed &&
                                event.currentTarget.contains(
                                  selection.anchorNode
                                ) &&
                                event.currentTarget.contains(
                                  selection.focusNode
                                )
                              )
                                return;
                              listScroll.current = currentScroll();
                              setSelectedSession({
                                date: activeDate,
                                key: historyIdentity(
                                  session.agent,
                                  session.session_id
                                ),
                              });
                            }}
                          >
                            <button
                              type="button"
                              className="history-session-select"
                              onClick={() => {
                                listScroll.current = currentScroll();
                                setSelectedSession({
                                  date: activeDate,
                                  key: historyIdentity(
                                    session.agent,
                                    session.session_id
                                  ),
                                });
                              }}
                            >
                              <span className="learnings-session-card-meta">
                                <Chip
                                  size="small"
                                  label={
                                    session.agent === "codex"
                                      ? "Codex"
                                      : "Claude Code"
                                  }
                                />
                                {SESSION_UUID.test(session.session_id) && (
                                  <span>
                                    Session {session.session_id.slice(0, 8)}
                                  </span>
                                )}
                                {session.computer_name && (
                                  <span>{session.computer_name}</span>
                                )}
                                <span>
                                  {localTime(session.first_time)} ·{" "}
                                  {session.entry_count} entries
                                </span>
                              </span>
                              <strong>{session.title}</strong>
                              {session.originals && (
                                <span className="history-availability">
                                  {session.originals.day_event_count} original
                                  events on this day
                                  {session.originals.active_day_count
                                    ? ` · ${session.originals.active_day_count} active days`
                                    : ""}
                                </span>
                              )}
                            </button>
                            {session.summary && (
                              <div className="learnings-session-card-summary">
                                <ReadableContent
                                  text={session.summary}
                                  kind="markdown"
                                />
                              </div>
                            )}
                          </article>
                        ) : (
                          <article
                            key={historyIdentity(
                              session.agent,
                              session.session_id
                            )}
                            className="learnings-session-card history-original-only"
                          >
                            <span className="learnings-session-card-meta">
                              <Chip
                                size="small"
                                label={
                                  session.agent === "codex"
                                    ? "Codex"
                                    : "Claude Code"
                                }
                              />
                              <span title={session.session_id}>
                                Session {session.session_id.slice(0, 8)}
                              </span>
                            </span>
                            <strong>{session.title}</strong>
                            <Typography variant="body2">
                              {dayQuery.isError
                                ? "Journal summary could not be loaded."
                                : "No journal summary yet."}
                            </Typography>
                            <Typography variant="caption">
                              {session.originals?.day_event_count} original
                              events on this day
                              {session.originals?.active_day_count
                                ? ` · ${session.originals.active_day_count} active days`
                                : ""}
                            </Typography>
                            <Button
                              size="small"
                              onClick={() =>
                                openEvidence(
                                  historyEvidenceLocation(
                                    folderId,
                                    session.originals!,
                                    activeDate!,
                                    timezone
                                  )
                                )
                              }
                            >
                              View originals
                            </Button>
                          </article>
                        )
                      )}
                      {originalSessions.hasNextPage && (
                        <Button
                          disabled={originalSessions.isFetchingNextPage}
                          onClick={() => void originalSessions.fetchNextPage()}
                        >
                          Load more sessions
                        </Button>
                      )}
                    </div>
                  ) : (
                    <>
                      <Button
                        size="small"
                        onClick={() => {
                          setSelectedSession(null);
                          restoreScroll(listScroll.current);
                        }}
                        sx={{ mb: 2 }}
                      >
                        ← All sessions
                      </Button>
                      <Typography sx={{ fontWeight: 650, mb: 0.5 }}>
                        {activeSession.title}
                      </Typography>
                      {activeSession.summary && (
                        <section
                          className="learnings-session-overview"
                          aria-label="Session overview"
                        >
                          <Typography
                            variant="caption"
                            sx={{ color: "text.secondary" }}
                          >
                            Session overview · updated as the session develops
                          </Typography>
                          <div className="learnings-session-card-summary">
                            <ReadableContent
                              text={activeSession.summary}
                              kind="markdown"
                            />
                          </div>
                        </section>
                      )}
                      <div className="learnings-timeline-track">
                        {visibleEntries.map((entry) => (
                          <article
                            key={entry.id}
                            id={`journal-entry-${entry.id}`}
                            className="learnings-entry"
                          >
                            <span
                              className={`learnings-entry-dot ${
                                entry.agent === "codex" ? "codex" : "claude"
                              }`}
                            />
                            <div className="learnings-entry-heading">
                              <time
                                dateTime={new Date(entry.time).toISOString()}
                              >
                                {localTime(entry.time)}
                              </time>
                              <Chip
                                size="small"
                                label={
                                  entry.agent === "codex"
                                    ? "Codex"
                                    : "Claude Code"
                                }
                              />
                              {entry.sessionId && (
                                <span
                                  className="learnings-session-id"
                                  title={`Resume with: ${
                                    entry.agent === "codex"
                                      ? "codex resume"
                                      : "claude --resume"
                                  } ${entry.sessionId}`}
                                  aria-label={`Session ID: ${entry.sessionId}`}
                                >
                                  Session {entry.sessionId.slice(0, 8)}
                                </span>
                              )}
                              {entry.computerName && (
                                <span
                                  className="learnings-session-id"
                                  title={`Computer: ${entry.computerName}`}
                                >
                                  {entry.computerName}
                                </span>
                              )}
                            </div>
                            <div className="learnings-markdown">
                              <ReadableContent
                                text={entry.markdown}
                                kind="markdown"
                              />
                            </div>
                            {activeSession.originals ? (
                              <Button
                                size="small"
                                onClick={() =>
                                  openEvidence(
                                    historyEvidenceLocation(
                                      folderId,
                                      activeSession.originals!,
                                      activeDate!,
                                      timezone
                                    )
                                  )
                                }
                              >
                                View evidence
                              </Button>
                            ) : (
                              <JournalEvidenceLink
                                folderId={folderId}
                                entryId={entry.id}
                                timezone={timezone}
                                onOpen={openEvidence}
                              />
                            )}
                          </article>
                        ))}
                      </div>
                    </>
                  )}
                </>
              )}
            </Box>
          </Box>
        </>
      ) : (
        <ReportsPanel
          folderId={folderId}
          onOpenHistory={(day, entryId) => void openSource(day, entryId)}
          onOpenEvidence={openEvidence}
        />
      )}
      <EvidenceDrawer
        location={evidenceLocation}
        onLocationChange={setEvidenceLocation}
        onClose={() => setEvidenceLocation(null)}
      />
    </Box>
  );
}
