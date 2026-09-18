/**
 * RefundButton — the GROUND-TRUTH refund action (SPEC §obol-console).
 *
 *   RefundButton → useRefund → POST /api/charges/:id/refunds
 *     → BFF refunds route → gateway POST /v1/charges/{id}/refunds.
 *
 * Renders a small inline form: pick a reason and (optionally) a partial amount,
 * confirm, and fire the refund. Disabled once the charge is already fully
 * refunded. Surfaces success/error inline so the operator gets immediate
 * feedback and can correlate failures via the request id in the error.
 */
import { useState } from 'react';
import type { Charge, RefundReason } from '@obol/contracts';
import { formatMoney, money } from '@obol/contracts';
import { useRefund } from '../hooks/useRefund.js';
import { ApiError } from '../api/http.js';

const REASONS: { value: RefundReason; label: string }[] = [
  { value: 'requested_by_customer', label: 'Requested by customer' },
  { value: 'duplicate', label: 'Duplicate charge' },
  { value: 'fraudulent', label: 'Fraudulent' },
  { value: 'product_not_received', label: 'Product not received' },
  { value: 'other', label: 'Other' },
];

export interface RefundButtonProps {
  charge: Charge;
}

export function RefundButton({ charge }: RefundButtonProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<RefundReason>('requested_by_customer');
  const [partial, setPartial] = useState('');
  const refund = useRefund();

  const alreadyRefunded = charge.status === 'refunded' || charge.status === 'failed';

  function submit(): void {
    const trimmed = partial.trim();
    const amount =
      trimmed === ''
        ? undefined
        : money(Math.round(Number.parseFloat(trimmed) * 100), charge.amount.currency);

    refund.mutate(
      { chargeId: charge.id, request: { reason, ...(amount ? { amount } : {}) } },
      { onSuccess: () => setOpen(false) },
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        className="btn btn--danger-outline"
        disabled={alreadyRefunded}
        onClick={() => setOpen(true)}
        aria-label={`Refund ${charge.id}`}
      >
        Refund
      </button>
    );
  }

  return (
    <div className="refund-form" role="group" aria-label={`Refund ${charge.id}`}>
      <label>
        Reason
        <select value={reason} onChange={(e) => setReason(e.target.value as RefundReason)}>
          {REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Amount ({charge.amount.currency}) — blank for full {formatMoney(charge.amount)}
        <input
          type="text"
          inputMode="decimal"
          placeholder="e.g. 30.00"
          value={partial}
          onChange={(e) => setPartial(e.target.value)}
        />
      </label>
      <div className="refund-form__actions">
        <button type="button" className="btn btn--danger" disabled={refund.isPending} onClick={submit}>
          {refund.isPending ? 'Refunding…' : 'Confirm refund'}
        </button>
        <button type="button" className="btn btn--ghost" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {refund.isError && (
        <p className="refund-form__error" role="alert">
          {refund.error instanceof ApiError
            ? `${refund.error.message} (request ${refund.error.requestId ?? 'n/a'})`
            : String(refund.error)}
        </p>
      )}
    </div>
  );
}
