/**
 * Event envelope + typed event bodies from SPEC §Events. The gateway publishes
 * these; the ledger consumes them. The console only ever *reads projections*
 * built from them — but the console's activity feeds render the same envelope,
 * so we mirror the shape here for display.
 *
 * All events share an envelope: `{ id, type, ts, data }`.
 * Consumers must be idempotent on `event.id`.
 */
import type { Money } from './money.js';

export type ObolEventType =
  | 'payment.authorized'
  | 'payment.settled'
  | 'refund.completed'
  | 'payout.scheduled'
  | 'payout.paid';

export interface EventEnvelope<T extends ObolEventType, D> {
  id: string;
  type: T;
  ts: string;
  data: D;
}

export interface PaymentAuthorizedData {
  charge_id: string;
  platform_id: string;
  seller_id: string;
  amount: Money;
  platform_fee: Money;
  processor_fee: Money;
}

export interface PaymentSettledData {
  charge_id: string;
  platform_id: string;
  seller_id: string;
  amount: Money;
  platform_fee: Money;
  processor_fee: Money;
}

export interface RefundCompletedData {
  refund_id: string;
  charge_id: string;
  amount: Money;
}

export interface PayoutScheduledData {
  batch_id: string;
  seller_id: string;
  amount: Money;
  scheduled_for: string;
}

export interface PayoutPaidData {
  batch_id: string;
  seller_id: string;
  amount: Money;
  processor_ref: string;
}

export type PaymentAuthorizedEvent = EventEnvelope<'payment.authorized', PaymentAuthorizedData>;
export type PaymentSettledEvent = EventEnvelope<'payment.settled', PaymentSettledData>;
export type RefundCompletedEvent = EventEnvelope<'refund.completed', RefundCompletedData>;
export type PayoutScheduledEvent = EventEnvelope<'payout.scheduled', PayoutScheduledData>;
export type PayoutPaidEvent = EventEnvelope<'payout.paid', PayoutPaidData>;

export type ObolEvent =
  | PaymentAuthorizedEvent
  | PaymentSettledEvent
  | RefundCompletedEvent
  | PayoutScheduledEvent
  | PayoutPaidEvent;

/** Narrowing helper for the activity feed. */
export function isRefundCompleted(e: ObolEvent): e is RefundCompletedEvent {
  return e.type === 'refund.completed';
}
