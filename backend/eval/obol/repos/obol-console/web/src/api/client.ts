/**
 * Typed console API client. One method per BFF endpoint. This is the SPA's whole
 * view of the backend — the ground-truth call chains route through here:
 *
 *   createRefund → POST /api/charges/:id/refunds  → BFF → gateway
 *   getSellerBalance → GET /api/sellers/:id/balance → BFF → ledger
 */
import type {
  BalanceResponse,
  ChargeDetailResponse,
  CreatePayoutBatchRequest,
  CreatePayoutBatchResponse,
  CreateRefundRequest,
  CreateRefundResponse,
  ListChargesQuery,
  ListChargesResponse,
  ListDisputesResponse,
  ListPayoutsResponse,
  Seller,
  StatementResponse,
} from '@obol/contracts';
import { apiFetch } from './http.js';

function qs(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined) usp.set(k, String(v));
  const s = usp.toString();
  return s ? `?${s}` : '';
}

export const consoleApi = {
  // --- Sellers ---
  listSellers(): Promise<{ sellers: Seller[] }> {
    return apiFetch('/sellers');
  },

  // --- Transactions (charges) ---
  listCharges(query: ListChargesQuery = {}): Promise<ListChargesResponse> {
    return apiFetch(
      `/charges${qs({
        seller_id: query.seller_id,
        status: query.status,
        limit: query.limit,
        cursor: query.cursor,
      })}`,
    );
  },
  getCharge(chargeId: string): Promise<ChargeDetailResponse> {
    return apiFetch(`/charges/${encodeURIComponent(chargeId)}`);
  },

  // --- Refund (GROUND-TRUTH refund action) ---
  createRefund(chargeId: string, req: CreateRefundRequest): Promise<CreateRefundResponse> {
    return apiFetch(`/charges/${encodeURIComponent(chargeId)}/refunds`, {
      method: 'POST',
      body: req,
    });
  },

  // --- Balances (GROUND-TRUTH balance display) ---
  getSellerBalance(sellerId: string): Promise<BalanceResponse> {
    return apiFetch(`/sellers/${encodeURIComponent(sellerId)}/balance`);
  },
  getSellerStatement(sellerId: string): Promise<StatementResponse> {
    return apiFetch(`/sellers/${encodeURIComponent(sellerId)}/statement`);
  },

  // --- Payouts ---
  listPayouts(sellerId?: string): Promise<ListPayoutsResponse> {
    return apiFetch(`/payouts${qs({ seller_id: sellerId })}`);
  },
  createPayoutBatch(req: CreatePayoutBatchRequest): Promise<CreatePayoutBatchResponse> {
    return apiFetch('/payouts', { method: 'POST', body: req });
  },

  // --- Disputes ---
  listDisputes(): Promise<ListDisputesResponse> {
    return apiFetch('/disputes');
  },
};

export type ConsoleApi = typeof consoleApi;
