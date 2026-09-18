/**
 * Money — the canonical value type from SPEC §Money.
 *
 * Money is ALWAYS integer minor units + an ISO-4217 currency. Never floats.
 * Field names mirror the spec's wire shape `{ amount_minor, currency }`, but on
 * the TypeScript side we expose the idiomatic camelCase `amountMinor`. The BFF's
 * upstream clients are responsible for translating between the two (see
 * `bff/src/clients/mapping.ts`).
 *
 *   Money { amountMinor: number; currency: string }   // e.g. { 4999, "EUR" } = €49.99
 */
export interface Money {
  /** Integer minor units (cents). 4999 === €49.99. Never fractional. */
  readonly amountMinor: number;
  /** ISO-4217 currency code, e.g. "EUR", "USD". */
  readonly currency: string;
}

/** Minor-unit exponents for the currencies Obol handles in the examples. */
const MINOR_UNIT_EXPONENT: Record<string, number> = {
  EUR: 2,
  USD: 2,
  GBP: 2,
  JPY: 0,
};

function exponentFor(currency: string): number {
  return MINOR_UNIT_EXPONENT[currency.toUpperCase()] ?? 2;
}

export function money(amountMinor: number, currency: string): Money {
  if (!Number.isInteger(amountMinor)) {
    throw new RangeError(`Money.amountMinor must be an integer, got ${amountMinor}`);
  }
  return { amountMinor, currency: currency.toUpperCase() };
}

export const zeroMoney = (currency: string): Money => money(0, currency);

/** Guard: arithmetic is only allowed between same-currency Money (SPEC §Money). */
export function assertSameCurrency(a: Money, b: Money): void {
  if (a.currency !== b.currency) {
    throw new Error(`Cross-currency operation rejected: ${a.currency} vs ${b.currency}`);
  }
}

export function addMoney(a: Money, b: Money): Money {
  assertSameCurrency(a, b);
  return money(a.amountMinor + b.amountMinor, a.currency);
}

export function subtractMoney(a: Money, b: Money): Money {
  assertSameCurrency(a, b);
  return money(a.amountMinor - b.amountMinor, a.currency);
}

export function isNegative(m: Money): boolean {
  return m.amountMinor < 0;
}

export function isZero(m: Money): boolean {
  return m.amountMinor === 0;
}

/**
 * Format Money for display, e.g. { 12000, "EUR" } → "€120.00".
 * Uses Intl so locale-correct currency symbols/grouping are applied.
 */
export function formatMoney(m: Money, locale = 'en-IE'): string {
  const exp = exponentFor(m.currency);
  const major = m.amountMinor / 10 ** exp;
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: m.currency,
      minimumFractionDigits: exp,
      maximumFractionDigits: exp,
    }).format(major);
  } catch {
    // Unknown currency code — fall back to a plain, unambiguous rendering.
    return `${major.toFixed(exp)} ${m.currency}`;
  }
}

/** Plain, symbol-free rendering: { 12000, "EUR" } → "120.00 EUR". */
export function formatMoneyPlain(m: Money): string {
  const exp = exponentFor(m.currency);
  return `${(m.amountMinor / 10 ** exp).toFixed(exp)} ${m.currency}`;
}
