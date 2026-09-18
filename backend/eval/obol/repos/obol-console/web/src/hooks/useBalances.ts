import { useQuery } from '@tanstack/react-query';
import { consoleApi } from '../api/client.js';

/**
 * GROUND-TRUTH BALANCE HOOK.
 * BalancePage → useBalances → consoleApi.getSellerBalance
 *   → GET /api/sellers/:id/balance → BFF → ledger GET /v1/accounts/{id}/balance.
 */
export function useBalances(sellerId: string | null) {
  return useQuery({
    queryKey: ['balance', sellerId],
    queryFn: () => consoleApi.getSellerBalance(sellerId as string),
    enabled: Boolean(sellerId),
    staleTime: 15_000,
  });
}

/** Seller statement (journal lines) for drill-down under the balance. */
export function useStatement(sellerId: string | null) {
  return useQuery({
    queryKey: ['statement', sellerId],
    queryFn: () => consoleApi.getSellerStatement(sellerId as string),
    enabled: Boolean(sellerId),
  });
}
