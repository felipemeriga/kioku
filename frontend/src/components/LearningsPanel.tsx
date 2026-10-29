import { useMemo, useState } from "react";
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
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { decorateJournalMarkdown } from "./journalMarkdown";
import { apiFetch } from "../lib/api";
import { brand, fonts } from "../theme";
import "./LearningsPanel.css";

type JournalDay = {
  journal_date: string;
  revision: number;
  entry_count: number;
  agents: string[];
};
type Learning = {
  id: string;
  topic_key: string;
  statement: string;
  status: "reported" | "committed";
  source_entries: { id: string; date: string; agent: string }[];
  git_sha: string | null;
  updated_at: string;
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
type JournalSession = {
  agent: string;
  session_id: string;
  title: string;
  summary: string;
  computer_name: string;
  entry_count: number;
  first_time: number;
  last_time: number;
};
const SESSION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function entriesFromMarkdown(markdown: string): Entry[] {
  const headings = [
    ...markdown.matchAll(
      /^## (?:Codex|Claude Code) session [^\n]+\n|^#{2,3} (\d\d:\d\d|\d{13}) — ([^\n]+)\n/gm,
    ),
  ];
  const entries: Entry[] = [];
  for (let i = 0; i < headings.length; i++) {
    const heading = headings[i];
    if (!heading[1]) continue;
    const section = markdown.slice(
      heading.index! + heading[0].length,
      i + 1 < headings.length ? headings[i + 1].index! : markdown.length,
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
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
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

export default function LearningsPanel({ folderId }: { folderId: string }) {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const [view, setView] = useState<"journal" | "learnings">("journal");
  const [month, setMonth] = useState(() => new Date().getMonth());
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const [selectedSession, setSelectedSession] = useState<{
    date: string;
    key: string;
  } | null>(null);

  const daysQuery = useQuery({
    queryKey: ["learning-days", folderId, year, month, timezone],
    queryFn: async () =>
      (await (
        await apiFetch(
          `/api/folders/${folderId}/learning-days?year=${year}&month=${month + 1}&timezone=${encodeURIComponent(timezone)}`,
        )
      ).json()) as { days: JournalDay[] },
    staleTime: 60_000,
  });
  const dayMap = useMemo(
    () =>
      new Map(
        (daysQuery.data?.days ?? []).map((day) => [day.journal_date, day]),
      ),
    [daysQuery.data],
  );
  const activeDate =
    selectedDate ?? daysQuery.data?.days[0]?.journal_date ?? null;
  const dayQuery = useQuery({
    queryKey: ["learning-day", folderId, activeDate, timezone],
    queryFn: async () =>
      (await (
        await apiFetch(
          `/api/folders/${folderId}/learning-days/${activeDate}?timezone=${encodeURIComponent(timezone)}`,
        )
      ).json()) as {
        status: string;
        markdown: string;
        revision: number;
        sessions?: JournalSession[];
      },
    enabled: !!activeDate && view === "journal",
    staleTime: 30_000,
  });
  const learningsQuery = useQuery({
    queryKey: ["repo-learnings", folderId],
    queryFn: async () =>
      (await (await apiFetch(`/api/folders/${folderId}/learnings`)).json()) as {
        learnings: Learning[];
      },
    enabled: view === "learnings",
    staleTime: 30_000,
  });

  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7;
  const count = new Date(year, month + 1, 0).getDate();
  const calendarCells = Array.from(
    { length: firstWeekday + count },
    (_, i) => i - firstWeekday + 1,
  );
  const monthLabel = new Intl.DateTimeFormat("en", {
    month: "long",
    year: "numeric",
  }).format(new Date(year, month, 1));
  const entries = entriesFromMarkdown(dayQuery.data?.markdown ?? "");
  const sessions =
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
        .values(),
    );
  const activeSession =
    selectedSession?.date === activeDate
      ? sessions.find(
          (session) =>
            `${session.agent}:${session.session_id}` === selectedSession.key,
        )
      : undefined;
  const visibleEntries = activeSession
    ? entries.filter((entry) => entry.sessionKey === selectedSession?.key)
    : [];

  const changeMonth = (step: number) => {
    const next = new Date(year, month + step, 1);
    setYear(next.getFullYear());
    setMonth(next.getMonth());
    setSelectedDate(null);
    setSelectedSession(null);
    setRaw(false);
  };
  const openSource = async (day: string, entryId: string) => {
    let viewerDay = day;
    try {
      const response = await apiFetch(
        `/api/folders/${folderId}/learning-days/${day}`,
      );
      const source = (await response.json()) as { markdown?: string };
      const entry = entriesFromMarkdown(source.markdown ?? "").find(
        (item) => item.id === entryId,
      );
      if (entry) viewerDay = localDay(entry.time);
    } catch {
      /* The original source day remains navigable if lookup fails. */
    }
    const [y, m] = viewerDay.split("-").map(Number);
    setYear(y);
    setMonth(m - 1);
    setSelectedDate(viewerDay);
    setSelectedSession(null);
    setRaw(false);
    setView("journal");
  };

  return (
    <Box className="learnings-panel">
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
            Project memory
          </Typography>
          <Typography sx={{ color: brand.muted, fontSize: 14 }}>
            Agent journal and current learnings from this repository.
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
          <Tab value="journal" label="Journal" />
          <Tab value="learnings" label="Learnings" />
        </Tabs>
      </Stack>

      {view === "journal" ? (
        <Box className="learnings-journal-layout">
          <Box className="learnings-calendar" aria-label="Journal calendar">
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
            {daysQuery.isLoading ? (
              <CircularProgress size={22} aria-label="Loading journal days" />
            ) : daysQuery.isError ? (
              <Alert severity="error">Could not load journal dates.</Alert>
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
                    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(date).padStart(2, "0")}`;
                    const day = dayMap.get(key);
                    return (
                      <button
                        key={key}
                        type="button"
                        className={`learnings-day ${activeDate === key ? "selected" : ""} ${day ? "has-entry" : ""}`}
                        aria-label={`${dateLabel(key)}${day ? `, ${day.entry_count} journal entries` : ", no entries"}`}
                        aria-pressed={activeDate === key}
                        onClick={() => {
                          setSelectedDate(key);
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
          </Box>

          <Box className="learnings-timeline">
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
                {activeDate && dayMap.get(activeDate) && (
                  <Typography sx={{ color: brand.muted, fontSize: 13 }}>
                    {dayMap.get(activeDate)?.entry_count} entries ·{" "}
                    {sessions.length} sessions · {timezone}
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
                Select a marked day to read the agent journal.
              </Typography>
            ) : dayQuery.isLoading ? (
              <Stack direction="row" gap={1} alignItems="center">
                <CircularProgress size={18} />
                Loading journal…
              </Stack>
            ) : dayQuery.isError ? (
              <Alert severity="error">Could not load this journal.</Alert>
            ) : dayQuery.data?.status !== "ok" ? (
              <Typography sx={{ color: brand.muted }}>
                No agent interactions recorded on this day.
              </Typography>
            ) : raw ? (
              <Box component="pre" className="learnings-raw">
                {dayQuery.data.markdown}
              </Box>
            ) : !activeSession ? (
              <div className="learnings-session-list">
                {sessions.map((session) => (
                  <button
                    key={`${session.agent}:${session.session_id}`}
                    type="button"
                    className="learnings-session-card"
                    onClick={() =>
                      setSelectedSession({
                        date: activeDate,
                        key: `${session.agent}:${session.session_id}`,
                      })
                    }
                  >
                    <span className="learnings-session-card-meta">
                      <Chip
                        size="small"
                        label={
                          session.agent === "codex" ? "Codex" : "Claude Code"
                        }
                      />
                      {SESSION_UUID.test(session.session_id) && (
                        <span>Session {session.session_id.slice(0, 8)}</span>
                      )}
                      {session.computer_name && (
                        <span>{session.computer_name}</span>
                      )}
                      <span>
                        {localTime(session.first_time)} · {session.entry_count}{" "}
                        entries
                      </span>
                    </span>
                    <strong>{session.title}</strong>
                    {session.summary && (
                      <div className="learnings-session-card-summary">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, decorateJournalMarkdown]}
                        >
                          {session.summary}
                        </ReactMarkdown>
                      </div>
                    )}
                  </button>
                ))}
              </div>
            ) : (
              <>
                <Button
                  size="small"
                  onClick={() => setSelectedSession(null)}
                  sx={{ mb: 2 }}
                >
                  ← All sessions
                </Button>
                <Typography sx={{ fontWeight: 650, mb: 0.5 }}>
                  {activeSession.title}
                </Typography>
                {activeSession.summary && (
                  <div className="learnings-session-card-summary">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, decorateJournalMarkdown]}
                    >
                      {activeSession.summary}
                    </ReactMarkdown>
                  </div>
                )}
                <div className="learnings-timeline-track">
                  {visibleEntries.map((entry) => (
                    <article key={entry.id} className="learnings-entry">
                      <span
                        className={`learnings-entry-dot ${entry.agent === "codex" ? "codex" : "claude"}`}
                      />
                      <div className="learnings-entry-heading">
                        <time dateTime={new Date(entry.time).toISOString()}>
                          {localTime(entry.time)}
                        </time>
                        <Chip
                          size="small"
                          label={
                            entry.agent === "codex" ? "Codex" : "Claude Code"
                          }
                        />
                        {entry.sessionId && (
                          <span
                            className="learnings-session-id"
                            title={`Resume with: ${entry.agent === "codex" ? "codex resume" : "claude --resume"} ${entry.sessionId}`}
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
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, decorateJournalMarkdown]}
                        >
                          {entry.markdown}
                        </ReactMarkdown>
                      </div>
                    </article>
                  ))}
                </div>
              </>
            )}
          </Box>
        </Box>
      ) : (
        <Box className="learnings-current">
          <Typography sx={{ color: brand.muted, mb: 2, maxWidth: 680 }}>
            These conclusions are maintained from new journal entries. Agent
            reports are identified until a matching commit is found on the
            principal branch.
          </Typography>
          {learningsQuery.isLoading ? (
            <Stack direction="row" gap={1} alignItems="center">
              <CircularProgress size={18} />
              Reviewing learnings…
            </Stack>
          ) : learningsQuery.isError ? (
            <Alert severity="error">Could not load learnings.</Alert>
          ) : !learningsQuery.data?.learnings.length ? (
            <Box className="learnings-empty">
              <Typography sx={{ fontWeight: 650 }}>No learnings yet</Typography>
              <Typography sx={{ color: brand.muted }}>
                Mihari will review new journal entries on its next pass.
              </Typography>
            </Box>
          ) : (
            <Stack gap={1.5}>
              {learningsQuery.data.learnings.map((learning) => (
                <article key={learning.id} className="learnings-card">
                  <Stack
                    direction="row"
                    justifyContent="space-between"
                    gap={2}
                    alignItems="flex-start"
                  >
                    <Typography
                      sx={{ fontSize: 16, lineHeight: 1.6, maxWidth: "75ch" }}
                    >
                      {learning.statement}
                    </Typography>
                    <Chip
                      size="small"
                      label={
                        learning.status === "committed"
                          ? "On main"
                          : "Agent report"
                      }
                      color={
                        learning.status === "committed" ? "success" : "warning"
                      }
                      variant="outlined"
                    />
                  </Stack>
                  <Stack
                    direction="row"
                    gap={1}
                    flexWrap="wrap"
                    sx={{ mt: 1.5 }}
                  >
                    {learning.source_entries.map((source) => (
                      <Button
                        key={source.id}
                        size="small"
                        onClick={() => void openSource(source.date, source.id)}
                      >
                        {source.date} ·{" "}
                        {source.agent === "codex" ? "Codex" : "Claude"}
                      </Button>
                    ))}
                    {learning.git_sha && (
                      <Typography
                        sx={{
                          color: brand.muted,
                          fontFamily: fonts.mono,
                          fontSize: 12,
                          alignSelf: "center",
                        }}
                      >
                        Commit {learning.git_sha.slice(0, 8)}
                      </Typography>
                    )}
                  </Stack>
                </article>
              ))}
            </Stack>
          )}
        </Box>
      )}
    </Box>
  );
}
