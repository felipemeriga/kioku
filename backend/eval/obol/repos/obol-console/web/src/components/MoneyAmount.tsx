/**
 * MoneyAmount — renders a Money value using the shared formatter (SPEC §Money).
 * The single place the UI turns `{ amountMinor, currency }` into a string, so
 * every screen formats money identically.
 */
import type { Money } from '@obol/contracts';
import { formatMoney, isNegative } from '@obol/contracts';

export interface MoneyAmountProps {
  value: Money;
  /** Add a +/- sign and colour for signed contexts (e.g. statement lines). */
  signed?: boolean;
  className?: string;
}

export function MoneyAmount({ value, signed = false, className }: MoneyAmountProps): JSX.Element {
  const text = formatMoney(value);
  const negative = isNegative(value);
  const display = signed && !negative ? `+${text}` : text;
  return (
    <span
      className={['money', negative ? 'money--negative' : 'money--positive', className]
        .filter(Boolean)
        .join(' ')}
      data-currency={value.currency}
      data-amount-minor={value.amountMinor}
      title={`${value.amountMinor} minor units ${value.currency}`}
    >
      {display}
    </span>
  );
}
