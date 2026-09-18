/**
 * PayoutTable — renders payout batches (SPEC §PayoutBatch).
 */
import type { PayoutBatch } from '@obol/contracts';
import { MoneyAmount } from './MoneyAmount.js';
import { StatusBadge } from './StatusBadge.js';

export interface PayoutTableProps {
  batches: PayoutBatch[];
  sellerNames?: Record<string, string>;
}

export function PayoutTable({ batches, sellerNames = {} }: PayoutTableProps): JSX.Element {
  if (batches.length === 0) {
    return <p className="empty">No payout batches yet.</p>;
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Batch</th>
          <th>Seller</th>
          <th className="num">Amount</th>
          <th>Status</th>
          <th>Scheduled for</th>
          <th>Processor ref</th>
        </tr>
      </thead>
      <tbody>
        {batches.map((b) => (
          <tr key={b.id}>
            <td className="mono">{b.id}</td>
            <td>{sellerNames[b.seller_id] ?? b.seller_id}</td>
            <td className="num">
              <MoneyAmount value={b.amount} />
            </td>
            <td>
              <StatusBadge status={b.status} />
            </td>
            <td>{new Date(b.scheduled_for).toLocaleDateString()}</td>
            <td className="mono">{b.processor_ref ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
