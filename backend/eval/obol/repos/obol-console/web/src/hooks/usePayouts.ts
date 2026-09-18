import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { CreatePayoutBatchRequest } from '@obol/contracts';
import { consoleApi } from '../api/client.js';

export function usePayouts(sellerId?: string) {
  return useQuery({
    queryKey: ['payouts', sellerId ?? 'all'],
    queryFn: () => consoleApi.listPayouts(sellerId),
    staleTime: 30_000,
  });
}

/** Schedule a payout batch (ledger builds from seller payable, calls gateway). */
export function useSchedulePayout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: CreatePayoutBatchRequest) => consoleApi.createPayoutBatch(req),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['payouts'] });
      void qc.invalidateQueries({ queryKey: ['balance'] });
    },
  });
}
