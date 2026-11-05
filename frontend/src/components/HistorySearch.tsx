import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import SearchIcon from "@mui/icons-material/Search";
import TuneIcon from "@mui/icons-material/Tune";
import { apiFetch, ApiError } from "../lib/api";
import "./HistorySearch.css";

import {
  emptyHistoryFilters,
  hasHistoryFilters,
  validateHistoryFilters,
  type HistoryFilters,
  type HistorySearchResponse,
  type HistorySearchSession,
} from "../lib/historySearch";
export function HistorySearchToolbar({
  filters,
  onChange,
}: {
  filters: HistoryFilters;
  onChange: (filters: HistoryFilters) => void;
}) {
  const [draft, setDraft] = useState(filters.q);
  const [advanced, setAdvanced] = useState(false);
  const errors = validateHistoryFilters({ ...filters, q: draft });
  const update = (key: keyof HistoryFilters, value: string) =>
    onChange({ ...filters, [key]: value });
  return (
    <Box className="history-search-toolbar">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!Object.keys(errors).length) update("q", draft.trim());
        }}
        className="history-search-query"
      >
        <SearchIcon sx={{ color: "text.secondary" }} />
        <TextField
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          error={!!errors.q}
          helperText={errors.q}
          placeholder="Search journal titles and content"
          inputProps={{ "aria-label": "Search history", maxLength: 160 }}
          size="small"
          fullWidth
        />
        <Button type="submit" variant="contained">
          Search
        </Button>
        <Button
          startIcon={<TuneIcon />}
          aria-expanded={advanced}
          onClick={() => setAdvanced(!advanced)}
        >
          Filters
        </Button>
      </form>
      <Stack
        direction="row"
        gap={1}
        flexWrap="wrap"
        alignItems="center"
        sx={{ mt: 1.5 }}
      >
        <Chip
          size="small"
          label={
            filters.date_from || filters.date_to
              ? `${filters.date_from || "Beginning"} – ${
                  filters.date_to || "Today"
                }`
              : "All dates"
          }
          onDelete={
            filters.date_from || filters.date_to
              ? () => onChange({ ...filters, date_from: "", date_to: "" })
              : undefined
          }
        />
        {filters.agent && (
          <Chip
            size="small"
            label={filters.agent === "codex" ? "Codex" : "Claude Code"}
            onDelete={() => update("agent", "")}
          />
        )}
        {filters.session_id && (
          <Chip
            size="small"
            label={`Session ${filters.session_id}`}
            onDelete={() => update("session_id", "")}
          />
        )}
        {hasHistoryFilters(filters) && (
          <Button
            size="small"
            onClick={() => {
              setDraft("");
              onChange({ ...emptyHistoryFilters });
            }}
          >
            Clear filters
          </Button>
        )}
      </Stack>
      <Collapse in={advanced}>
        <Box className="history-search-filters">
          <TextField
            select
            label="Match"
            value={filters.mode}
            onChange={(e) => update("mode", e.target.value)}
            size="small"
          >
            <MenuItem value="words">All words</MenuItem>
            <MenuItem value="phrase">Exact phrase</MenuItem>
            <MenuItem value="regex">Regex</MenuItem>
          </TextField>
          <TextField
            select
            label="Search in"
            value={filters.fields}
            onChange={(e) => update("fields", e.target.value)}
            size="small"
          >
            <MenuItem value="all">All journal content</MenuItem>
            <MenuItem value="title">Titles only</MenuItem>
          </TextField>
          <TextField
            select
            label="Agent"
            value={filters.agent}
            onChange={(e) => update("agent", e.target.value)}
            size="small"
          >
            <MenuItem value="">All agents</MenuItem>
            <MenuItem value="codex">Codex</MenuItem>
            <MenuItem value="claude_code">Claude Code</MenuItem>
          </TextField>
          <TextField
            error={!!errors.session_id}
            helperText={errors.session_id}
            label="Session ID"
            value={filters.session_id}
            onChange={(e) => update("session_id", e.target.value)}
            size="small"
            inputProps={{ maxLength: 256 }}
          />
          <TextField
            error={!!errors.date_from}
            helperText={errors.date_from}
            label="From"
            type="date"
            value={filters.date_from}
            onChange={(e) => update("date_from", e.target.value)}
            size="small"
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            error={!!errors.date_to}
            helperText={errors.date_to}
            label="Through"
            type="date"
            value={filters.date_to}
            onChange={(e) => update("date_to", e.target.value)}
            size="small"
            slotProps={{ inputLabel: { shrink: true } }}
          />
        </Box>
      </Collapse>
    </Box>
  );
}

// Highlight literal terms only. User regular expressions never execute in the UI thread.
export function SearchExcerpt({
  text,
  filters,
}: {
  text: string;
  filters: HistoryFilters;
}) {
  const terms =
    filters.mode === "regex"
      ? []
      : filters.mode === "phrase"
      ? [filters.q.toLowerCase()]
      : filters.q.toLowerCase().split(/\s+/).filter(Boolean);
  const lower = text.toLowerCase();
  const nodes = [];
  let start = 0,
    plain = 0;
  while (start < text.length && terms.length) {
    const term = terms.find((t) => t && lower.startsWith(t, start));
    if (term) {
      if (plain < start) nodes.push(text.slice(plain, start));
      nodes.push(
        <mark key={start}>{text.slice(start, start + term.length)}</mark>
      );
      start += term.length;
      plain = start;
    } else start++;
  }
  nodes.push(text.slice(plain));
  return <>{nodes}</>;
}

export function HistorySearchResults({
  folderId,
  userId,
  timezone,
  filters,
  onOpen,
}: {
  folderId: string;
  userId?: string;
  timezone: string;
  filters: HistoryFilters;
  onOpen: (
    session: HistorySearchSession,
    date: string,
    entryId?: string
  ) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [indexing, setIndexing] = useState(false);
  const [indexError, setIndexError] = useState("");
  const indexOlder = async () => {
    setIndexing(true);
    setIndexError("");
    try {
      await apiFetch(
        `/api/folders/${encodeURIComponent(
          folderId
        )}/history-search/backfill?limit=10`,
        { method: "POST" }
      );
      await query.refetch();
    } catch (error) {
      setIndexError(
        error instanceof Error
          ? error.message
          : "Indexing failed. Please retry."
      );
    } finally {
      setIndexing(false);
    }
  };
  const validationErrors = validateHistoryFilters(filters);
  const invalidDates = Object.keys(validationErrors).length > 0;
  const query = useQuery({
    queryKey: ["history-search", folderId, userId, timezone, filters, offset],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({
        ...filters,
        timezone,
        limit: "20",
        offset: String(offset),
      });
      for (const [key, value] of [...params.entries()])
        if (!value) params.delete(key);
      return (await (
        await apiFetch(
          `/api/folders/${encodeURIComponent(
            folderId
          )}/history-search?${params}`,
          { signal }
        )
      ).json()) as HistorySearchResponse;
    },
    enabled: !invalidDates,
    retry: false,
    staleTime: 30_000,
  });
  if (invalidDates)
    return (
      <Alert severity="warning">
        {Object.values(validationErrors).join(" ")}
      </Alert>
    );
  return (
    <Box className="history-search-results">
      {indexError && <Alert severity="error">{indexError}</Alert>}
      {query.isPending ? (
        <Stack direction="row" gap={1} role="status">
          <CircularProgress size={18} />
          Searching history…
        </Stack>
      ) : query.isError ? (
        <Alert
          severity="error"
          action={
            !(
              query.error instanceof ApiError &&
              query.error.status >= 400 &&
              query.error.status < 500
            ) ? (
              <Button onClick={() => void query.refetch()}>Retry</Button>
            ) : undefined
          }
        >
          <strong>Could not search history.</strong>
          <br />
          {query.error.message}
        </Alert>
      ) : (
        <>
          <Typography component="h3" sx={{ fontSize: 18, fontWeight: 650 }}>
            {query.data.total_sessions}{" "}
            {query.data.total_sessions === 1 ? "session" : "sessions"}{" "}
            <Box
              component="span"
              sx={{ color: "text.secondary", fontWeight: 400, fontSize: 13 }}
            >
              · {query.data.total_entries} matching journal{" "}
              {query.data.total_entries === 1 ? "entry" : "entries"}
            </Box>
          </Typography>
          {!!query.data.coverage?.pending_days && (
            <Alert
              severity="info"
              sx={{ mt: 2 }}
              action={
                <Button disabled={indexing} onClick={() => void indexOlder()}>
                  {indexing ? "Indexing…" : "Index older journals"}
                </Button>
              }
            >
              Older journal days need indexing. Results may be incomplete.
            </Alert>
          )}
          {!query.data.sessions.length && (
            <Box className="history-search-empty">
              <SearchIcon />
              <Typography>No matching history</Typography>
              <Typography variant="body2" color="text.secondary">
                Try fewer words or broaden the date and agent filters.
              </Typography>
            </Box>
          )}
          {query.data.sessions.map((session) => (
            <article
              className="history-search-card"
              key={`${session.agent}:${session.session_id}`}
            >
              <Stack
                direction="row"
                gap={1}
                flexWrap="wrap"
                alignItems="center"
              >
                <Chip
                  size="small"
                  label={session.agent === "codex" ? "Codex" : "Claude Code"}
                />
                <Typography variant="caption" title={session.session_id}>
                  Session {session.session_id.slice(0, 8)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {session.dates.length} active days
                </Typography>
              </Stack>
              <Button
                className="history-search-title"
                onClick={() =>
                  onOpen(
                    session,
                    session.matches[0]?.date ||
                      session.dates[session.dates.length - 1]
                  )
                }
              >
                <span>
                  <SearchExcerpt text={session.title} filters={filters} />
                </span>
              </Button>
              <Stack direction="row" gap={1}>
                {session.title_match && (
                  <Chip size="small" variant="outlined" label="Title match" />
                )}
                {session.overview_match && (
                  <Chip
                    size="small"
                    variant="outlined"
                    label="Overview match"
                  />
                )}
              </Stack>
              {session.overview_match && session.summary && (
                <Typography variant="body2" color="text.secondary">
                  <SearchExcerpt text={session.summary} filters={filters} />
                </Typography>
              )}
              {session.matches.map((match) => (
                <button
                  type="button"
                  className="history-search-excerpt"
                  key={match.id}
                  onClick={() => onOpen(session, match.date, match.id)}
                >
                  <time>{match.date}</time>
                  <span>
                    <SearchExcerpt text={match.excerpt} filters={filters} />
                  </span>
                </button>
              ))}
            </article>
          ))}
          <Stack direction="row" justifyContent="space-between" sx={{ mt: 2 }}>
            <Button
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous
            </Button>
            <Button
              disabled={!query.data.has_more}
              onClick={() => setOffset(offset + 20)}
            >
              Next sessions
            </Button>
          </Stack>
        </>
      )}
    </Box>
  );
}
