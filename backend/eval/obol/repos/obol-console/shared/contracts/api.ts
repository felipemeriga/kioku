/**
 * API request/response DTOs exchanged between the web SPA and the BFF. These are
 * the console's own contract (BFF ⇄ web), distinct from the upstream
 * gateway/ledger wire formats which the BFF clients adapt to/from.
 */
import type { Money } from './money.js';
import type {
  AccountBalance,
  AccountStatement,
  Charge,
  Dispute,
  PayoutBatch,
  Refund,
  RefundReason,
} from './entities.js';

// --- Refunds (web → BFF → gateway POST /v1/charges/{id}/refunds) --------------

export interface CreateRefundRequest {
  /** Omit `amount` for a full refund; provide it for a partial refund. */
  amount?: Money;
  reason: RefundReason;
}

export interface CreateRefundResponse {
  refund: Refund;
  /** Charge status after the refund posts: refunded | partially_refunded. */
  charge_status: Charge['status'];
}

// --- Charges / transactions ---------------------------------------------------

export interface ListChargesQuery {
  seller_id?: string;
  status?: Charge['status'];
  limit?: number;
  cursor?: string;
}

export interface ListChargesResponse {
  charges: Charge[];
  next_cursor: string | null;
}

export interface ChargeDetailResponse {
  charge: Charge;
  refunds: Refund[];
}

// --- Balances / statements (web → BFF → ledger) -------------------------------

export interface BalanceResponse {
  balance: AccountBalance;
  /** The seller this account belongs to, for display convenience. */
  seller_id: string;
}

export type StatementResponse = AccountStatement;

// --- Payouts ------------------------------------------------------------------

export interface ListPayoutsResponse {
  batches: PayoutBatch[];
}

export interface CreatePayoutBatchRequest {
  seller_id: string;
  scheduled_for?: string;
}

export interface CreatePayoutBatchResponse {
  batch: PayoutBatch;
}

// --- Disputes -----------------------------------------------------------------

export interface ListDisputesResponse {
  disputes: Dispute[];
}

// --- Errors (uniform BFF error envelope) --------------------------------------

export interface ApiErrorBody {
  error: {
    /** Stable machine code, e.g. "upstream_error", "not_found". */
    code: string;
    message: string;
    /** Correlates with the `x-request-id` response header. */
    request_id: string;
    /** Upstream HTTP status, when the failure originated upstream. */
    upstream_status?: number;
  };
}
