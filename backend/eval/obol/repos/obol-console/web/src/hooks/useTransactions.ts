import { useQuery } from '@tanstack/react-query';
import type { ListChargesQuery } from '@obol/contracts';
import { consoleApi } from '../api/client.js';

/** Transactions (charges) feed for the TransactionsPage. */
export function useTransactions(query: ListChargesQuery = {}) {
  return useQuery({
    queryKey: ['charges', query],
    queryFn: () => consoleApi.listCharges(query),
    staleTime: 30_000,
  });
}

/** Single charge detail (charge + its refunds). */
export function useChargeDetail(chargeId: string | null) {
  return useQuery({
    queryKey: ['charge', chargeId],
    queryFn: () => consoleApi.getCharge(chargeId as string),
    enabled: Boolean(chargeId),
  });
}
