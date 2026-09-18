import { useQuery } from '@tanstack/react-query';
import { consoleApi } from '../api/client.js';

/** Roster of the platform's sellers (for pickers on Balance/Payouts screens). */
export function useSellers() {
  return useQuery({
    queryKey: ['sellers'],
    queryFn: () => consoleApi.listSellers(),
    staleTime: 5 * 60_000,
  });
}
