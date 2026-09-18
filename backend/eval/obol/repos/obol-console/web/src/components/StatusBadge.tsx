/**
 * StatusBadge — coloured pill for charge / refund / payout / dispute statuses.
 * The status literals match the SPEC entity unions exactly.
 */
import type {
  ChargeStatus,
  DisputeStatus,
  PayoutBatchStatus,
  RefundStatus,
} from '@obol/contracts';

type AnyStatus = ChargeStatus | RefundStatus | PayoutBatchStatus | DisputeStatus;

const TONE: Record<AnyStatus, 'neutral' | 'info' | 'success' | 'warn' | 'danger'> = {
  // charge
  pending: 'neutral',
  authorized: 'info',
  settled: 'success',
  failed: 'danger',
  refunded: 'warn',
  partially_refunded: 'warn',
  // refund
  completed: 'success',
  // payout batch
  scheduled: 'info',
  processing: 'info',
  paid: 'success',
  // dispute
  open: 'warn',
  won: 'success',
  lost: 'danger',
};

export interface StatusBadgeProps {
  status: AnyStatus;
}

export function StatusBadge({ status }: StatusBadgeProps): JSX.Element {
  const tone = TONE[status] ?? 'neutral';
  const label = status.replace(/_/g, ' ');
  return (
    <span className={`badge badge--${tone}`} data-status={status}>
      {label}
    </span>
  );
}
