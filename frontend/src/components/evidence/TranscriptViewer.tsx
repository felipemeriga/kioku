import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  MenuItem,
  Select,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { ApiError } from "../../lib/api";
import {
  evidenceKeys,
  type EvidenceLocation,
} from "../../lib/agentEvidenceApi";
import { useSessionEvidence } from "../../hooks/useSessionEvidence";
import SessionIdentity from "./SessionIdentity";
import TranscriptEvent, { RawTranscriptRecord } from "./TranscriptEvent";
import "./evidence.css";

function dateLabel(value: string, timezone: string) {
  return new Intl.DateTimeFormat(undefined, {
    timeZone: timezone,
    dateStyle: "long",
  }).format(new Date(value));
}
export default function TranscriptViewer({
  location,
  onLocationChange,
  variant = "page",
}: {
  location: EvidenceLocation;
  onLocationChange: (location: EvidenceLocation) => void;
  variant?: "page" | "drawer";
}) {
  const { session, days, window: source } = useSessionEvidence(location);
  const queryClient = useQueryClient();
  const scroll = useRef<HTMLDivElement>(null);
  const data = session.data;
  const pages = source.data?.pages ?? [];
  const events = [
    ...new Map(
      pages
        .flatMap((page) => page.events ?? [])
        .map((event) => [event.event_id, event]),
    ).values(),
  ];
  const records = [
    ...new Map(
      pages
        .flatMap((page) => page.records ?? [])
        .map((event) => [event.event_id, event]),
    ).values(),
  ];
  const visibleIds = (location.mode === "raw" ? records : events).map(
    (row) => row.event_id,
  );
  const rangeStart = visibleIds.indexOf(location.eventId ?? "");
  const rangeEnd = visibleIds.indexOf(location.endEventId ?? "");
  const selected = (id: string) => {
    const index = visibleIds.indexOf(id);
    return rangeStart >= 0 && rangeEnd >= rangeStart
      ? index >= rangeStart && index <= rangeEnd
      : id === location.eventId || id === location.endEventId;
  };
  const restoredAnchor = useRef<string | null>(null);
  const anchorKey = `${location.sessionId}:${location.mode}:${
    location.eventId ?? ""
  }`;
  useEffect(() => {
    if (
      !location.eventId ||
      !visibleIds.includes(location.eventId) ||
      restoredAnchor.current === anchorKey
    )
      return;
    const target = [
      ...(scroll.current?.querySelectorAll<HTMLElement>("[data-event-id]") ??
        []),
    ].find((row) => row.dataset.eventId === location.eventId);
    if (target && scroll.current) {
      scroll.current.scrollTop +=
        target.getBoundingClientRect().top -
        scroll.current.getBoundingClientRect().top;
      restoredAnchor.current = anchorKey;
    }
  }, [anchorKey, location.eventId, visibleIds]);
  const indexedRevision = pages[0]?.snapshot_revision;
  const processing = pages.some(
    (page) => page.status === "processing" || page.status === "pending",
  );
  const refresh = () =>
    queryClient.resetQueries({
      queryKey: evidenceKeys.window(location),
      exact: true,
    });
  const move = (value: Partial<EvidenceLocation>) =>
    onLocationChange({ ...location, ...value });
  const earlier = async () => {
    const el = scroll.current;
    const anchor =
      el &&
      [...el.querySelectorAll<HTMLElement>("[data-event-id]")].find(
        (row) =>
          row.getBoundingClientRect().bottom > el.getBoundingClientRect().top,
      );
    const anchorId = anchor?.dataset.eventId;
    const anchorTop = anchor?.getBoundingClientRect().top;
    const height = el?.scrollHeight ?? 0;
    const top = el?.scrollTop ?? 0;
    await source.fetchPreviousPage();
    requestAnimationFrame(() => {
      if (!el) return;
      const retained = [
        ...el.querySelectorAll<HTMLElement>("[data-event-id]"),
      ].find((row) => row.dataset.eventId === anchorId);
      el.scrollTop =
        retained && anchorTop !== undefined
          ? el.scrollTop + retained.getBoundingClientRect().top - anchorTop
          : top + el.scrollHeight - height;
    });
  };
  if (session.isLoading)
    return (
      <Stack direction="row" gap={1} sx={{ p: 3 }}>
        <CircularProgress size={20} />
        Loading original evidence…
      </Stack>
    );
  if (session.isError) {
    const status = session.error instanceof ApiError ? session.error.status : 0;
    return (
      <Alert
        severity={status === 404 || status === 410 ? "info" : "error"}
        action={<Button onClick={() => void session.refetch()}>Retry</Button>}
      >
        {status === 404
          ? "Original evidence is unavailable for this session, or archival is not enabled yet."
          : status === 410
          ? "Original evidence was deleted. The journal summary is still available."
          : String(session.error)}
      </Alert>
    );
  }
  if (!data) return null;
  const navigateDay = (day: string) =>
    move({ date: day, eventId: undefined, endEventId: undefined });
  const child = (id: string) =>
    move({
      sessionId: id,
      eventId: undefined,
      endEventId: undefined,
      date: undefined,
      mode: "conversation",
    });
  const dayNavigation = (
    <>
      <Stack direction="row" alignItems="center" gap={0.5} sx={{ mb: 1 }}>
        <Typography sx={{ fontSize: 13 }}>Active session days</Typography>
        <Tooltip
          title="Only active days are listed. Idle days are not evidence gaps."
          describeChild
        >
          <IconButton size="small" aria-label="About active session days">
            <InfoOutlinedIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      </Stack>
      {days.isLoading && (
        <CircularProgress size={16} aria-label="Loading session days" />
      )}
      {days.isError && (
        <Button size="small" onClick={() => void days.refetch()}>
          Retry dates
        </Button>
      )}
      {(days.data?.days ?? []).map((day) => (
        <Button
          key={day.date}
          className="evidence-day-button"
          aria-pressed={location.date === day.date}
          onClick={() => navigateDay(day.date)}
        >
          <span>{day.date}</span>
          <span>{day.event_count} events</span>
        </Button>
      ))}
    </>
  );
  let lastDay: string | undefined;
  return (
    <section
      className={`evidence-viewer evidence-${variant}`}
      aria-label="Original transcript"
    >
      <header className="evidence-heading">
        <Typography
          component="h1"
          sx={{
            fontSize: variant === "drawer" ? 20 : 28,
            fontWeight: 600,
            mb: 1,
          }}
        >
          {data.title || "Original transcript"}
        </Typography>
        <SessionIdentity agent={data.agent} nativeId={data.native_session_id} />
        {location.approximate && (
          <Alert severity="info">
            Approximate session context. An exact source range for this journal
            entry is unavailable.
          </Alert>
        )}
        <Typography variant="body2" sx={{ mt: 1 }}>
          {data.first_event_at
            ? dateLabel(data.first_event_at, location.timezone)
            : "First event time unknown"}
          {data.last_event_at &&
            ` – ${dateLabel(data.last_event_at, location.timezone)}`}
          {data.active_day_count !== undefined &&
            ` · ${data.active_day_count} active days`}
        </Typography>
        <Typography variant="caption">
          {data.last_event_at
            ? `Last archived event ${new Intl.DateTimeFormat(undefined, {
                timeZone: location.timezone,
                dateStyle: "medium",
                timeStyle: "short",
              }).format(new Date(data.last_event_at))}`
            : "Capture registered; event times are not available"}{" "}
          · {location.timezone}
        </Typography>
        {data.parent_session_id && (
          <Button size="small" onClick={() => child(data.parent_session_id!)}>
            Back to parent
          </Button>
        )}
        {data.capture_status === "deleted" && (
          <Alert severity="info">Original evidence was deleted.</Alert>
        )}
        {data.index_status !== "ready" && data.index_status !== "indexed" && (
          <Typography role="status" variant="caption">
            Index status: {data.index_status}. The journal remains available.
          </Typography>
        )}
        {(data.gaps ?? []).map((gap, index) => (
          <Alert key={`${gap.code}-${index}`} severity="warning" sx={{ mt: 1 }}>
            {gap.message || gap.code.replaceAll("_", " ")}
          </Alert>
        ))}
      </header>
      <div className="evidence-reader-layout">
        {variant === "page" && (
          <aside className="evidence-day-sidebar">{dayNavigation}</aside>
        )}
        <div className="evidence-reading-column">
          <Stack
            className="evidence-toolbar"
            direction="row"
            gap={1}
            alignItems="center"
            justifyContent="space-between"
            flexWrap="wrap"
          >
            <ToggleButtonGroup
              size="small"
              exclusive
              value={location.mode}
              onChange={(_, mode: "conversation" | "raw" | null) =>
                mode && move({ mode })
              }
              aria-label="Original evidence presentation"
            >
              <ToggleButton value="conversation">Reading</ToggleButton>
              <ToggleButton value="raw">Raw source</ToggleButton>
            </ToggleButtonGroup>
            <Select
              size="small"
              displayEmpty
              value={location.date ?? ""}
              inputProps={{ "aria-label": "Jump to session day" }}
              onChange={(event) => navigateDay(event.target.value)}
              sx={{ fontSize: 13, minWidth: 150 }}
            >
              <MenuItem value="" disabled>
                Jump to date
              </MenuItem>
              {(days.data?.days ?? []).map((day) => (
                <MenuItem key={day.date} value={day.date}>
                  {day.date}
                </MenuItem>
              ))}
            </Select>
          </Stack>
          {indexedRevision != null &&
            data.indexed_revision > indexedRevision && (
              <Button onClick={() => void refresh()}>
                New evidence available · refresh this window
              </Button>
            )}
          {source.isLoading ? (
            <Stack direction="row" gap={1} sx={{ p: 2 }}>
              <CircularProgress size={18} />
              Loading source window…
            </Stack>
          ) : source.isError ? (
            <Alert
              severity="error"
              action={
                <Button onClick={() => void refresh()}>Reload source</Button>
              }
            >
              {source.error instanceof ApiError && source.error.status === 409
                ? "The source window changed. Reload to continue without skipping events."
                : "Could not load this source window."}
            </Alert>
          ) : (
            <div className="evidence-reader-events" ref={scroll}>
              {location.endEventId && (rangeStart < 0 || rangeEnd < 0) && (
                <Alert severity="info">
                  The linked evidence range continues outside this loaded
                  window. Only visible boundary events are highlighted.
                </Alert>
              )}
              {source.hasPreviousPage && (
                <Button
                  fullWidth
                  onClick={() => void earlier()}
                  disabled={source.isFetchingPreviousPage}
                >
                  Load earlier
                </Button>
              )}
              {processing && (
                <Alert severity="info">
                  Original evidence is still processing. The journal summary is
                  available.
                </Alert>
              )}
              {!processing && !events.length && !records.length && (
                <Typography sx={{ p: 2 }}>
                  No original events are available in this window.
                </Typography>
              )}
              {location.mode === "raw"
                ? records.map((record) => (
                    <RawTranscriptRecord
                      key={record.event_id}
                      record={record}
                      location={location}
                      selected={selected(record.event_id)}
                    />
                  ))
                : events.map((event) => {
                    const day = event.event_at
                      ? new Intl.DateTimeFormat("en-CA", {
                          timeZone: location.timezone,
                          dateStyle: "short",
                        }).format(new Date(event.event_at))
                      : undefined;
                    const separator = day && day !== lastDay;
                    if (day) lastDay = day;
                    return (
                      <Box key={event.event_id}>
                        {separator && (
                          <Typography
                            component="h2"
                            className="evidence-date-divider"
                          >
                            {dateLabel(event.event_at!, location.timezone)}
                          </Typography>
                        )}
                        <TranscriptEvent
                          event={event}
                          location={location}
                          selected={selected(event.event_id)}
                          onChild={child}
                          linkedCall={
                            event.call_id &&
                            events.some(
                              (other) =>
                                other.event_id !== event.event_id &&
                                other.call_id === event.call_id &&
                                /call/.test(other.event_type) !==
                                  /call/.test(event.event_type) &&
                                !!other.event_at &&
                                !!event.event_at &&
                                new Intl.DateTimeFormat("en-CA", {
                                  timeZone: location.timezone,
                                }).format(new Date(other.event_at)) ===
                                  new Intl.DateTimeFormat("en-CA", {
                                    timeZone: location.timezone,
                                  }).format(new Date(event.event_at)),
                            )
                              ? event.call_id
                              : undefined
                          }
                        />
                      </Box>
                    );
                  })}
              {source.hasNextPage && (
                <Button
                  fullWidth
                  onClick={() => void source.fetchNextPage()}
                  disabled={source.isFetchingNextPage}
                >
                  Load later
                </Button>
              )}
              <Typography className="evidence-window-note" variant="caption">
                Only a bounded source window is loaded. Storage segment
                boundaries do not split the conversation.
              </Typography>
            </div>
          )}
          {!!data.children?.length && (
            <details className="evidence-children">
              <summary>Child sessions ({data.children.length})</summary>
              {data.children.map((item) => (
                <Button
                  key={item.id}
                  size="small"
                  onClick={() => child(item.id)}
                >
                  {item.agent === "codex" ? "Codex" : "Claude Code"} ·{" "}
                  {item.native_session_id} · View child evidence
                </Button>
              ))}
            </details>
          )}
        </div>
      </div>
    </section>
  );
}
