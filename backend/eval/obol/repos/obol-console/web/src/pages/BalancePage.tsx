/**
 * BalancePage — the GROUND-TRUTH balance display (SPEC §obol-console).
 *
 *   BalancePage → useBalances → GET /api/sellers/:id/balance
 *     → BFF balances route → ledger GET /v1/accounts/{id}/balance.
 *
 * Pick a seller; the page shows the ledger-derived available/pending payable
 * balance and the recent statement lines from the immutable journal.
 */
import { useState } from 'react';
import { useBalances, useStatement } from '../hooks/useBalances.js';
import { useSellers } from '../hooks/useSellers.js';
import { SellerPicker } from '../components/SellerPicker.js';
import { MoneyAmount } from '../components/MoneyAmount.js';
import { QueryState } from '../components/QueryState.js';

export function BalancePage(): JSX.Element {
  const sellers = useSellers();
  const [sellerId, setSellerId] = useState<string | null>(null);

  const balance = useBalances(sellerId);
  const statement = useStatement(sellerId);

  return (
    <section>
      <header className="page-header">
        <h1>Balances</h1>
        <p className="page-subtitle">
          Seller payable balances, read straight from the ledger (
          <code>seller_payable:&#123;seller_id&#125;</code>).
        </p>
      </header>

      <QueryState isLoading={sellers.isLoading} isError={sellers.isError} error={sellers.error}>
        <SellerPicker sellers={sellers.data?.sellers ?? []} value={sellerId} onChange={setSellerId} />
      </QueryState>

      {sellerId && (
        <>
          <QueryState isLoading={balance.isLoading} isError={balance.isError} error={balance.error}>
            {balance.data && (
              <div className="balance-cards">
                <article className="card">
                  <h2>Available</h2>
                  <p className="card__amount">
                    <MoneyAmount value={balance.data.balance.available} />
                  </p>
                  <small className="card__meta">Account {balance.data.balance.account_id}</small>
                </article>
                <article className="card">
                  <h2>Pending</h2>
                  <p className="card__amount">
                    <MoneyAmount value={balance.data.balance.pending} />
                  </p>
                  <small className="card__meta">
                    As of {new Date(balance.data.balance.as_of).toLocaleString()}
                  </small>
                </article>
              </div>
            )}
          </QueryState>

          <h2 className="section-title">Statement</h2>
          <QueryState isLoading={statement.isLoading} isError={statement.isError} error={statement.error}>
            {statement.data && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Entry</th>
                    <th>Posted</th>
                    <th>Memo</th>
                    <th className="num">Debit</th>
                    <th className="num">Credit</th>
                    <th className="num">Running balance</th>
                  </tr>
                </thead>
                <tbody>
                  {statement.data.lines.map((l) => (
                    <tr key={l.entry_id}>
                      <td className="mono">{l.entry_id}</td>
                      <td>{new Date(l.posted_at).toLocaleDateString()}</td>
                      <td>{l.memo}</td>
                      <td className="num">{l.debit ? <MoneyAmount value={l.debit} /> : '—'}</td>
                      <td className="num">{l.credit ? <MoneyAmount value={l.credit} /> : '—'}</td>
                      <td className="num">
                        <MoneyAmount value={l.running_balance} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </QueryState>
        </>
      )}
    </section>
  );
}
