/**
 * Verifies the GROUND-TRUTH refund ACTION on the web side:
 *   RefundButton → useRefund → consoleApi.createRefund (mocked) → POST
 *   /api/charges/:id/refunds. We assert the button calls the client with the
 *   right charge id + reason and that a fully-refunded charge disables it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RefundButton } from '../components/RefundButton.js';
import { sampleCharge } from '../fixtures/sampleData.js';
import { consoleApi } from '../api/client.js';

vi.mock('../api/client.js', () => ({
  consoleApi: {
    createRefund: vi.fn(),
  },
}));

const createRefund = consoleApi.createRefund as unknown as ReturnType<typeof vi.fn>;

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('RefundButton (ground-truth refund action)', () => {
  beforeEach(() => {
    createRefund.mockReset();
  });

  it('drives consoleApi.createRefund with the charge id and reason', async () => {
    createRefund.mockResolvedValue({
      refund: {
        id: 'rfnd_x',
        charge_id: sampleCharge.id,
        amount: sampleCharge.amount,
        reason: 'requested_by_customer',
        status: 'completed',
        created_at: '2026-02-20T00:00:00Z',
      },
      charge_status: 'refunded',
    });

    const user = userEvent.setup();
    wrap(<RefundButton charge={sampleCharge} />);

    await user.click(screen.getByRole('button', { name: /refund chg_0001/i }));
    await user.click(screen.getByRole('button', { name: /confirm refund/i }));

    await waitFor(() => expect(createRefund).toHaveBeenCalledTimes(1));
    expect(createRefund).toHaveBeenCalledWith('chg_0001', {
      reason: 'requested_by_customer',
    });
  });

  it('is disabled for an already fully-refunded charge', () => {
    wrap(<RefundButton charge={{ ...sampleCharge, status: 'refunded' }} />);
    expect(screen.getByRole('button', { name: /refund chg_0001/i })).toBeDisabled();
  });
});
