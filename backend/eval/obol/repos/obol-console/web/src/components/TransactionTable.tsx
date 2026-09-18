/**
 * TransactionTable — renders charges with per-row RefundButton. This is the
 * table the TransactionsPage builds around.
 */
import type { Charge } from '@obol/contracts';
import { MoneyAmount } from './MoneyAmount.js';
import { StatusBadge } from './StatusBadge.js';
import { RefundButton } from './RefundButton.js';

export interface TransactionTableProps {
  charges: Charge[];
  sellerNames?: Record<string, string>;
}

export function TransactionTable({ charges, sellerNames = {} }: TransactionTableProps): JSX.Element {
  if (charges.length === 0) {
    return <p className="empty">No transactions match the current filters.</p>;
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Charge</th>
          <th>Seller</th>
          <th className="num">Amount</th>
          <th className="num">Platform fee</th>
          <th className="num">Processor fee</th>
          <th>Status</th>
          <th>Created</th>
          <th aria-label="Actions" />
        </tr>
      </thead>
      <tbody>
        {charges.map((c) => (
          <tr key={c.id}>
            <td className="mono">{c.id}</td>
            <td>{sellerNames[c.seller_id] ?? c.seller_id}</td>
            <td className="num">
              <MoneyAmount value={c.amount} />
            </td>
            <td className="num">
              <MoneyAmount value={c.platform_fee} />
            </td>
            <td className="num">
              <MoneyAmount value={c.processor_fee} />
            </td>
            <td>
              <StatusBadge status={c.status} />
            </td>
            <td>{new Date(c.created_at).toLocaleDateString()}</td>
            <td className="actions">
              <RefundButton charge={c} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
