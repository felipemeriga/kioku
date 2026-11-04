import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  evidenceKeys,
  evidenceRetry,
  getEvidenceDays,
  getEvidenceSession,
  getEvidenceWindow,
  type EvidenceLocation,
  type EvidenceWindowOptions,
} from "../lib/agentEvidenceApi";

/** At most three bounded windows are retained; originals never load as a whole. */
export function useSessionEvidence(location: EvidenceLocation) {
  const session = useQuery({
    queryKey: evidenceKeys.session(location.folderId, location.sessionId),
    queryFn: ({ signal }) =>
      getEvidenceSession(location.folderId, location.sessionId, signal),
    staleTime: 30_000,
    refetchInterval: 15_000,
    retry: evidenceRetry,
  });
  const days = useQuery({
    queryKey: evidenceKeys.days(
      location.folderId,
      location.sessionId,
      location.timezone,
    ),
    queryFn: ({ signal }) =>
      getEvidenceDays(
        location.folderId,
        location.sessionId,
        location.timezone,
        signal,
      ),
    enabled: !!session.data,
    staleTime: 30_000,
    retry: evidenceRetry,
  });
  const window = useInfiniteQuery({
    queryKey: evidenceKeys.window(location),
    initialPageParam: {
      around: location.eventId,
      date: location.date,
      timezone: location.timezone,
      limit: 50,
    } as EvidenceWindowOptions,
    queryFn: ({ pageParam, signal }) =>
      getEvidenceWindow(location, pageParam, signal),
    getNextPageParam: (page) =>
      page.next_cursor
        ? {
            after: page.next_cursor,
            timezone: location.timezone,
            snapshot_revision: page.snapshot_revision,
            limit: 50,
          }
        : undefined,
    getPreviousPageParam: (page) =>
      page.previous_cursor
        ? {
            before: page.previous_cursor,
            timezone: location.timezone,
            snapshot_revision: page.snapshot_revision,
            limit: 50,
          }
        : undefined,
    maxPages: 3,
    enabled: !!session.data,
    retry: evidenceRetry,
    staleTime: 30_000,
    refetchInterval: (query) =>
      query.state.data?.pages.some(
        (page) => page.status === "processing" || page.status === "pending",
      )
        ? 3000
        : false,
  });
  return { session, days, window };
}
