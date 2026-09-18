import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { CreateRefundRequest, CreateRefundResponse } from '@obol/contracts';
import { consoleApi } from '../api/client.js';

export interface RefundVariables {
  chargeId: string;
  request: CreateRefundRequest;
}

/**
 * GROUND-TRUTH REFUND HOOK.
 * RefundButton → useRefund → consoleApi.createRefund
 *   → POST /api/charges/:id/refunds → BFF refunds route
 *     → gateway POST /v1/charges/{id}/refunds (→ processor → refund.completed
 *       → ledger reversal).
 *
 * On success we invalidate the charges + charge-detail + balance queries so the
 * UI reflects the new charge status and the seller's reduced payable balance.
 */
export function useRefund() {
  const qc = useQueryClient();
  return useMutation<CreateRefundResponse, Error, RefundVariables>({
    mutationFn: ({ chargeId, request }) => consoleApi.createRefund(chargeId, request),
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: ['charges'] });
      void qc.invalidateQueries({ queryKey: ['charge', variables.chargeId] });
      void qc.invalidateQueries({ queryKey: ['balance'] });
    },
  });
}
