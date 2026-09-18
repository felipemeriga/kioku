/**
 * PayoutsPage — list payout batches and schedule new ones. Scheduling a batch
 * asks the ledger to build it from the seller's payable balance (which then
 * calls the gateway to move money).
 */
import { useMemo, useState } from 'react';
import { usePayouts, useSchedulePayout } from '../hooks/usePayouts.js';
import { useSellers } from '../hooks/useSellers.js';
import { SellerPicker } from '../components/SellerPicker.js';
import { PayoutTable } from '../components/PayoutTable.js';
import { QueryState } from '../components/QueryState.js';
import { ApiError } from '../api/http.js';

export function PayoutsPage(): JSX.Element {
  const sellers = useSellers();
  const [sellerId, setSellerId] = useState<string | null>(null);
  const payouts = usePayouts(sellerId ?? undefined);
  const schedule = useSchedulePayout();

  const sellerNames = useMemo(() => {
    const map: Record<string, string> = {};
    for (const s of sellers.data?.sellers ?? []) map[s.id] = s.display_name;
    return map;
  }, [sellers.data]);

  return (
    <section>
      <header className="page-header">
        <h1>Payouts</h1>
        <p className="page-subtitle">Scheduled movements of seller balances to their banks.</p>
      </header>

      <div className="filters">
        <QueryState isLoading={sellers.isLoading} isError={sellers.isError} error={sellers.error}>
          <SellerPicker
            sellers={sellers.data?.sellers ?? []}
            value={sellerId}
            onChange={setSellerId}
            label="Filter by seller"
          />
        </QueryState>
        <button
          type="button"
          className="btn btn--primary"
          disabled={!sellerId || schedule.isPending}
          onClick={() => sellerId && schedule.mutate({ seller_id: sellerId })}
        >
          {schedule.isPending ? 'Scheduling…' : 'Schedule payout'}
        </button>
      </div>

      {schedule.isError && (
        <p className="error" role="alert">
          {schedule.error instanceof ApiError
            ? `${schedule.error.message} (request ${schedule.error.requestId ?? 'n/a'})`
            : String(schedule.error)}
        </p>
      )}

      <QueryState isLoading={payouts.isLoading} isError={payouts.isError} error={payouts.error}>
        <PayoutTable batches={payouts.data?.batches ?? []} sellerNames={sellerNames} />
      </QueryState>
    </section>
  );
}
