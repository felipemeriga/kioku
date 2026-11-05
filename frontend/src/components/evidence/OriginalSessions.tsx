import { useInfiniteQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import { Link, useLocation } from "react-router-dom";
import { ApiError } from "../../lib/api";
import {
  evidenceUrl,
  evidenceRetry,
  listEvidenceSessions,
  type EvidenceLocation,
} from "../../lib/agentEvidenceApi";
import SessionIdentity from "./SessionIdentity";
import "./evidence.css";

export default function OriginalSessions({
  folderId,
  timezone,
  onOpen,
  onBeforeNavigate,
}: {
  folderId: string;
  timezone: string;
  onOpen: (location: EvidenceLocation) => void;
  onBeforeNavigate?: () => void;
}) {
  const route = useLocation();
  const sessions = useInfiniteQuery({
    queryKey: ["agent-evidence-session-list", folderId],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      listEvidenceSessions(folderId, pageParam, signal),
    getNextPageParam: (page) => page.next_cursor || undefined,
    maxPages: 3,
    retry: evidenceRetry,
  });
  if (sessions.isLoading)
    return (
      <Stack direction="row" gap={1}>
        <CircularProgress size={18} />
        Loading original sessions…
      </Stack>
    );
  if (sessions.isError)
    return (
      <Alert
        severity={
          sessions.error instanceof ApiError && sessions.error.status === 404
            ? "info"
            : "error"
        }
        action={<Button onClick={() => void sessions.refetch()}>Retry</Button>}
      >
        {sessions.error instanceof ApiError && sessions.error.status === 404
          ? "Original evidence archival is not available on this server yet."
          : "Could not load original sessions."}
      </Alert>
    );
  const rows =
    sessions.data?.pages.flatMap((page) => page.sessions ?? []) ?? [];
  return (
    <section aria-label="Original sessions" className="evidence-session-list">
      <Typography variant="body2">
        Original conversations are retained independently of journal summaries.
        Sessions without a summary appear here too.
      </Typography>
      {!rows.length && (
        <Typography>
          No original sessions have been captured for this repository.
        </Typography>
      )}
      {rows.map((session) => {
        const location: EvidenceLocation = {
          folderId,
          sessionId: session.id,
          timezone,
          mode: "conversation",
        };
        return (
          <article key={session.id} className="evidence-session-card">
            <SessionIdentity
              agent={session.agent}
              nativeId={session.native_session_id}
            />
            <Typography sx={{ fontSize: 17, fontWeight: 600, my: 1 }}>
              {session.title || "Original session"}
            </Typography>
            {session.summary && (
              <Typography variant="body2">{session.summary}</Typography>
            )}
            <Typography variant="caption">
              {session.event_count} events
              {session.active_day_count !== undefined
                ? ` · ${session.active_day_count} active days`
                : ""}{" "}
              · {session.capture_status}
            </Typography>
            {!!session.gaps?.length && (
              <Typography variant="body2">
                Evidence gaps recorded ({session.gaps.length})
              </Typography>
            )}
            <Stack direction="row" gap={1}>
              <Button size="small" onClick={() => onOpen(location)}>
                View originals
              </Button>
              <Button
                size="small"
                component={Link}
                onClick={onBeforeNavigate}
                to={evidenceUrl(location)}
                state={{ evidenceReturnTo: route.pathname + route.search }}
              >
                Open full transcript
              </Button>
            </Stack>
          </article>
        );
      })}
      {sessions.hasNextPage && (
        <Button
          disabled={sessions.isFetchingNextPage}
          onClick={() => void sessions.fetchNextPage()}
        >
          Load older sessions
        </Button>
      )}
    </section>
  );
}
