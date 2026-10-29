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
  computerName: string;
  time: string;
  markdown: string;
};
const SESSION_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function entriesFromMarkdown(markdown: string): Entry[] {
  const sections = markdown.split(/^## (\d\d:\d\d) — ([^\n]+)\n/gm);
  const entries: Entry[] = [];
  for (let i = 1; i + 2 < sections.length; i += 3) {
    const marker = sections[i + 2].match(
      /^<!-- kioku-entry: (\{[^\n]+\}) -->\n/m,
    );
    if (!marker) continue;
    try {
      const meta = JSON.parse(marker[1]) as {
        id: string;
        agent: string;
        session_id?: string;
        computer_name?: string;
      };
      entries.push({
        id: meta.id,
        agent: meta.agent,
        sessionId:
          typeof meta.session_id === "string" &&
          SESSION_UUID.test(meta.session_id)
            ? meta.session_id
            : "",
        time: sections[i],
        computerName:
          typeof meta.computer_name === "string" ? meta.computer_name : "",
        markdown: sections[i + 2].replace(marker[0], "").trim(),
      });
    } catch {
      /* An invalid entry stays visible in raw Markdown. */
    }
  }
  return entries.sort((a, b) => a.time.localeCompare(b.time));
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
  const [view, setView] = useState<"journal" | "learnings">("journal");
  const [month, setMonth] = useState(() => new Date().getMonth());
  const [year, setYear] = useState(() => new Date().getFullYear());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);

  const daysQuery = useQuery({
    queryKey: ["learning-days", folderId, year],
    queryFn: async () =>
      (await (
        await apiFetch(`/api/folders/${folderId}/learning-days?year=${year}`)
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
    queryKey: ["learning-day", folderId, activeDate],
    queryFn: async () =>
      (await (
        await apiFetch(`/api/folders/${folderId}/learning-days/${activeDate}`)
      ).json()) as { status: string; markdown: string; revision: number },
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

  const changeMonth = (step: number) => {
    const next = new Date(year, month + step, 1);
    setYear(next.getFullYear());
    setMonth(next.getMonth());
  };
  const openSource = (day: string) => {
    const [y, m] = day.split("-").map(Number);
    setYear(y);
    setMonth(m - 1);
    setSelectedDate(day);
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
                    {dayMap.get(activeDate)?.entry_count} entries · revision{" "}
                    {dayMap.get(activeDate)?.revision}
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
            ) : (
              <div className="learnings-timeline-track">
                {entries.map((entry) => (
                  <article key={entry.id} className="learnings-entry">
                    <span
                      className={`learnings-entry-dot ${entry.agent === "codex" ? "codex" : "claude"}`}
                    />
                    <div className="learnings-entry-heading">
                      <time>{entry.time}</time>
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
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {entry.markdown}
                      </ReactMarkdown>
                    </div>
                  </article>
                ))}
              </div>
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
                        onClick={() => openSource(source.date)}
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
