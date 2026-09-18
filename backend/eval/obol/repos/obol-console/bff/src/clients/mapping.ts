/**
 * Translation between upstream wire shapes and the console's TypeScript
 * contracts. Upstream services speak snake_case Money `{ amount_minor, currency }`
 * (SPEC §Money). Internally the console uses `{ amountMinor, currency }`. This
 * module is the one place that knows about that difference.
 */
import type { Money } from '@obol/contracts';

/** Upstream Money as it appears on the gateway/ledger wire. */
export interface WireMoney {
  amount_minor: number;
  currency: string;
}

export function toMoney(w: WireMoney): Money {
  return { amountMinor: w.amount_minor, currency: w.currency };
}

export function fromMoney(m: Money): WireMoney {
  return { amount_minor: m.amountMinor, currency: m.currency };
}

/** Map any object's `*_money` fields recursively is overkill here; we map
 * explicitly per-entity to keep types honest. Helper for optional Money. */
export function toMoneyMaybe(w: WireMoney | null | undefined): Money | null {
  return w ? toMoney(w) : null;
}
