/**
 * Core entities, field-for-field from SPEC §"Core entities". These are the
 * projections the console reads (gateway owns charges/refunds, ledger owns
 * balances/statements/payout batches). Field names deliberately match the spec.
 */
import type { Money } from './money.js';

// --- Enums / literal unions ---------------------------------------------------

export type KycStatus = 'pending' | 'verified' | 'rejected';

export type ChargeStatus =
  | 'pending'
  | 'authorized'
  | 'settled'
  | 'failed'
  | 'refunded'
  | 'partially_refunded';

export type RefundStatus = 'pending' | 'completed' | 'failed';

export type RefundReason =
  | 'requested_by_customer'
  | 'duplicate'
  | 'fraudulent'
  | 'product_not_received'
  | 'other';

export type PayoutBatchStatus = 'scheduled' | 'processing' | 'paid' | 'failed';

export type DisputeStatus = 'open' | 'won' | 'lost';

// --- Entities -----------------------------------------------------------------

/** SPEC: Platform — Obol's customer (the marketplace). */
export interface Platform {
  id: string;
  name: string;
  country: string;
  default_platform_fee_bps: number;
  created_at: string;
}

/** SPEC: Seller — a sub-merchant selling on the platform. */
export interface Seller {
  id: string;
  platform_id: string;
  display_name: string;
  kyc_status: KycStatus;
  payout_currency: string;
  created_at: string;
}

/** SPEC: Charge — a buyer payment. */
export interface Charge {
  id: string;
  platform_id: string;
  seller_id: string;
  amount: Money;
  platform_fee: Money;
  processor_fee: Money;
  status: ChargeStatus;
  idempotency_key: string;
  processor_ref: string;
  created_at: string;
}

/** SPEC: Refund — reverses all or part of a charge. */
export interface Refund {
  id: string;
  charge_id: string;
  amount: Money;
  reason: RefundReason;
  status: RefundStatus;
  created_at: string;
}

/** SPEC: PayoutBatch — scheduled movement of a seller's balance to their bank. */
export interface PayoutBatch {
  id: string;
  seller_id: string;
  amount: Money;
  status: PayoutBatchStatus;
  scheduled_for: string;
  processor_ref: string | null;
  created_at: string;
}

/** SPEC: Dispute — a buyer chargeback against a charge. */
export interface Dispute {
  id: string;
  charge_id: string;
  amount: Money;
  status: DisputeStatus;
  created_at: string;
}

// --- Ledger projections (read by the console via the BFF → ledger) -----------

/**
 * Balance for a ledger account, as returned by ledger
 * `GET /v1/accounts/{account_id}/balance`. `seller_payable:{seller_id}` is the
 * account whose balance the BalancePage renders.
 */
export interface AccountBalance {
  account_id: string;
  available: Money;
  pending: Money;
  as_of: string;
}

/** A single line of a ledger statement (SPEC §Ledger model, JournalLine). */
export interface StatementLine {
  entry_id: string;
  posted_at: string;
  memo: string;
  debit: Money | null;
  credit: Money | null;
  running_balance: Money;
}

/** Ledger `GET /v1/accounts/{account_id}/statement`. */
export interface AccountStatement {
  account_id: string;
  currency: string;
  opening_balance: Money;
  closing_balance: Money;
  lines: StatementLine[];
}
