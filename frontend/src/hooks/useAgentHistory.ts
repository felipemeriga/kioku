import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { fetchHistoryDays, fetchHistorySessions } from "../lib/agentHistoryApi";
import { ApiError } from "../lib/api";
export const historyUnsupported = (error: unknown) =>
  error instanceof ApiError && [404, 503].includes(error.status);
const retry = (failures: number, error: unknown) =>
  failures < 1 && !historyUnsupported(error);
export function useOriginalHistoryDays(
  folderId: string,
  userId: string | undefined,
  year: number,
  month: number,
  timezone: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["agent-history-days", userId, folderId, year, month, timezone],
    queryFn: ({ signal }) =>
      fetchHistoryDays(folderId, year, month, timezone, signal),
    enabled,
    staleTime: 30_000,
    retry,
  });
}
export function useOriginalHistorySessions(
  folderId: string,
  userId: string | undefined,
  date: string | null,
  timezone: string,
  enabled: boolean,
) {
  return useInfiniteQuery({
    queryKey: ["agent-history-sessions", userId, folderId, date, timezone],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      fetchHistorySessions(folderId, date!, timezone, pageParam, signal),
    getNextPageParam: (page) => page.next_cursor || undefined,
    enabled: enabled && !!date,
    staleTime: 30_000,
    retry,
  });
}
