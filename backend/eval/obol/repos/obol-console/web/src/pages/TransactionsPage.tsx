/**
 * TransactionsPage — the charges ledger with inline refund actions. Filters by
 * seller and status; each row's RefundButton drives the ground-truth refund
 * path (→ BFF → gateway).
 */
import { useMemo, useState } from 'react';
import type { Charge } from '@obol/contracts';
import { useTransactions } from '../hooks/useTransactions.js';
import { useSellers } from '../hooks/useSellers.js';
import { TransactionTable } from '../components/TransactionTable.js';
import { QueryState } from '../components/QueryState.js';

const STATUSES: (Charge['status'] | '')[] = [
  '',
  'pending',
  'authorized',
  'settled',
  'partially_refunded',
  'refunded',
  'failed',
];

export function TransactionsPage(): JSX.Element {
  const [status, setStatus] = useState<Charge['status'] | ''>('');
  const [sellerId, setSellerId] = useState<string>('');

  const charges = useTransactions({
    ...(status ? { status } : {}),
    ...(sellerId ? { seller_id: sellerId } : {}),
  });
  const sellers = useSellers();

  const sellerNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const s of sellers.data?.sellers ?? []) map[s.id] = s.display_name;
    return map;
  }, [sellers.data]);

  return (
    <section>
      <header className="page-header">
        <h1>Transactions</h1>
        <p className="page-subtitle">All charges across the platform. Refunds route through the gateway.</p>
      </header>

      <div className="filters">
        <label>
          Seller
          <select value={sellerId} onChange={(e) => setSellerId(e.target.value)}>
            <option value="">All sellers</option>
            {(sellers.data?.sellers ?? []).map((s) => (
              <option key={s.id} value={s.id}>
                {s.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value as Charge['status'] | '')}>
            {STATUSES.map((s) => (
              <option key={s || 'all'} value={s}>
                {s === '' ? 'All statuses' : s.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
        </label>
      </div>

      <QueryState isLoading={charges.isLoading} isError={charges.isError} error={charges.error}>
        <TransactionTable charges={charges.data?.charges ?? []} sellerNames={sellerNames} />
      </QueryState>
    </section>
  );
}
