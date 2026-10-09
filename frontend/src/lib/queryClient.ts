import { QueryClient } from "@tanstack/react-query";

/**
 * Shared React Query client config. Tuned for "instant on reopen, but still
 * fresh": a short staleTime means revisiting a folder/conversation paints the
 * cached data immediately and triggers a quiet background refetch (so newly
 * added items show up), while gcTime keeps the cache warm between visits.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 10_000, // 10s — lists feel instant on reopen, still refetch
        gcTime: 5 * 60_000, // keep cached data for 5min of instant revisits
        retry: 1,
        refetchOnWindowFocus: true,
      },
    },
  });
}

export const queryClient = makeQueryClient();
