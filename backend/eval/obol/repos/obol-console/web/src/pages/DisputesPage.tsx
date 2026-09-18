/**
 * DisputesPage — buyer chargebacks (SPEC §Dispute) against charges.
 */
import { useDisputes } from '../hooks/useDisputes.js';
import { MoneyAmount } from '../components/MoneyAmount.js';
import { StatusBadge } from '../components/StatusBadge.js';
import { QueryState } from '../components/QueryState.js';

export function DisputesPage(): JSX.Element {
  const disputes = useDisputes();

  return (
    <section>
      <header className="page-header">
        <h1>Disputes</h1>
        <p className="page-subtitle">Chargebacks raised by buyers against settled charges.</p>
      </header>

      <QueryState isLoading={disputes.isLoading} isError={disputes.isError} error={disputes.error}>
        {(disputes.data?.disputes ?? []).length === 0 ? (
          <p className="empty">No disputes. 🎉</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Dispute</th>
                <th>Charge</th>
                <th className="num">Amount</th>
                <th>Status</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {(disputes.data?.disputes ?? []).map((d) => (
                <tr key={d.id}>
                  <td className="mono">{d.id}</td>
                  <td className="mono">{d.charge_id}</td>
                  <td className="num">
                    <MoneyAmount value={d.amount} />
                  </td>
                  <td>
                    <StatusBadge status={d.status} />
                  </td>
                  <td>{new Date(d.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryState>
    </section>
  );
}
